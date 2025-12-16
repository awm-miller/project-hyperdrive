"""
VPS Manager - Commands to manage workers
Supports both local mode (running on VPS) and remote mode (via SSH)
"""

import os
import subprocess
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


class VPSManager:
    """Manages VPS for worker operations. Supports local and SSH modes."""

    def __init__(self):
        self.host = os.getenv("VPS_HOST", "localhost")
        self.project_path = os.getenv("VPS_PROJECT_PATH", "/opt/project-hyperdrive")
        
        # Worker config - loaded from dashboard env
        self.gemini_api_key = os.getenv("GEMINI_API_KEY", "")
        self.mullvad_account = os.getenv("MULLVAD_ACCOUNT", "")
        
        # Local mode if running on VPS itself (no host specified or localhost)
        self.local_mode = self.host in ["localhost", "127.0.0.1", ""]
        
        # SSH mode setup
        if not self.local_mode:
            import paramiko
            self.user = os.getenv("VPS_USER", "root")
            self.ssh_key = os.path.expanduser(os.getenv("VPS_SSH_KEY", "~/.ssh/id_rsa"))
            self._client = None

    def _connect(self):
        """Get or create SSH connection (remote mode only)."""
        if self.local_mode:
            return None
        import paramiko
        if self._client is None or not self._client.get_transport() or not self._client.get_transport().is_active():
            self._client = paramiko.SSHClient()
            self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self._client.connect(
                hostname=self.host,
                username=self.user,
                key_filename=self.ssh_key
            )
        return self._client

    def run_command(self, cmd: str) -> tuple[str, str, int]:
        """Run command, return (stdout, stderr, exit_code)."""
        if self.local_mode:
            # Run locally via subprocess
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            return result.stdout, result.stderr, result.returncode
        else:
            # Run via SSH
            client = self._connect()
            stdin, stdout, stderr = client.exec_command(cmd)
            exit_code = stdout.channel.recv_exit_status()
            return stdout.read().decode(), stderr.read().decode(), exit_code

    def get_env_vars(self) -> str:
        """Get export command for env vars."""
        return f"cd {self.project_path} && export $(grep -v '^#' .env | xargs)"

    # ==================== WORKER OPERATIONS ====================

    def list_workers(self) -> list[dict]:
        """List all running worker containers."""
        cmd = "docker ps --filter 'name=worker' --format '{{.Names}}|{{.Status}}|{{.Image}}'"
        stdout, _, _ = self.run_command(cmd)
        workers = []
        for line in stdout.strip().split('\n'):
            if line:
                parts = line.split('|')
                workers.append({
                    "name": parts[0],
                    "status": parts[1] if len(parts) > 1 else "unknown",
                    "image": parts[2] if len(parts) > 2 else "unknown"
                })
        return workers

    def restart_worker(self, worker_id: str) -> tuple[bool, str]:
        """Restart a worker container."""
        cmd = f"docker restart worker-{worker_id}"
        stdout, stderr, code = self.run_command(cmd)
        return code == 0, stdout or stderr

    def stop_worker(self, worker_id: str) -> tuple[bool, str]:
        """Stop a worker container."""
        cmd = f"docker stop worker-{worker_id}"
        stdout, stderr, code = self.run_command(cmd)
        return code == 0, stdout or stderr

    def get_worker_logs(self, worker_id: str, lines: int = 50) -> str:
        """Get recent logs from a worker."""
        cmd = f"docker logs worker-{worker_id} 2>&1 | tail -{lines}"
        stdout, _, _ = self.run_command(cmd)
        return stdout

    def get_worker_vpn_status(self, worker_id: str) -> dict:
        """Get VPN status for a worker."""
        cmd = f"docker exec worker-{worker_id} mullvad status 2>&1"
        stdout, _, code = self.run_command(cmd)
        if code == 0 and "Connected" in stdout:
            # Parse the output
            lines = stdout.strip().split('\n')
            status = {"connected": True}
            for line in lines:
                if "Relay:" in line:
                    status["relay"] = line.split(":")[-1].strip()
                if "Visible location:" in line:
                    status["location"] = line.split(":")[-1].strip()
            return status
        return {"connected": False, "error": stdout}

    def spin_up_worker(self, worker_num: int) -> tuple[bool, str]:
        """Spin up a new worker with associated Nitter and Redis."""
        # Validate config
        if not self.gemini_api_key:
            return False, "GEMINI_API_KEY not configured in dashboard environment"
        if not self.mullvad_account:
            return False, "MULLVAD_ACCOUNT not configured in dashboard environment"
        
        redis_name = f"nitter-redis-{worker_num}"
        nitter_name = f"nitter-{worker_num}"
        worker_name = f"worker-{worker_num}"
        
        # Step 1: Create Nitter config if doesn't exist
        self.run_command(f"cp -n {self.project_path}/nitter-worker1.conf {self.project_path}/nitter-worker{worker_num}.conf 2>/dev/null || true")
        
        # Step 2: Update Redis host in config (only if not worker 1)
        if worker_num != 1:
            self.run_command(f"sed -i 's/nitter-redis-1/nitter-redis-{worker_num}/g' {self.project_path}/nitter-worker{worker_num}.conf")
        
        # Step 3: Start or create nitter-redis (try start first, create if doesn't exist)
        self.run_command(
            f"docker start {redis_name} 2>/dev/null || "
            f"docker run -d --name {redis_name} --network project-hyperdrive_default "
            f"redis:7-alpine redis-server --save 60 1 --loglevel warning"
        )
        
        # Step 4: Start or create nitter
        self.run_command(
            f"docker start {nitter_name} 2>/dev/null || "
            f"docker run -d --name {nitter_name} --network project-hyperdrive_default "
            f"-v {self.project_path}/nitter-worker{worker_num}.conf:/src/nitter.conf:ro "
            f"-v {self.project_path}/sessions.jsonl:/src/sessions.jsonl:ro "
            f"zedeus/nitter:latest"
        )
        
        # Wait for nitter to be ready
        self.run_command("sleep 5")
        
        # Step 5: Remove existing worker and create fresh
        self.run_command(f"docker rm -f {worker_name} 2>/dev/null || true")
        
        worker_cmd = (
            f"docker run -d --name {worker_name} "
            f"--network project-hyperdrive_default "
            f"-v /var/run/docker.sock:/var/run/docker.sock "
            f"-e REDIS_URL=redis://redis-queue:6379 "
            f"-e NITTER_URL=http://nitter-{worker_num}:8080 "
            f"-e NITTER_REDIS_HOST=nitter-redis-{worker_num} "
            f"-e GEMINI_API_KEY={self.gemini_api_key} "
            f"-e MULLVAD_ACCOUNT={self.mullvad_account} "
            f"--cap-add=NET_ADMIN "
            f"--device=/dev/net/tun "
            f"project-hyperdrive_worker-1"
        )
        stdout, stderr, code = self.run_command(worker_cmd)
        if code != 0:
            return False, f"Worker start failed: {stderr or stdout}"
        
        # Wait 10 seconds for worker to initialize
        self.run_command("sleep 10")
        
        # Connect Mullvad VPN
        vpn_cmd = f"docker exec worker-{worker_num} mullvad connect"
        stdout, stderr, code = self.run_command(vpn_cmd)
        
        if code != 0:
            return True, f"Worker started but VPN connect failed: {stderr or stdout}"
        
        return True, f"Worker-{worker_num} started successfully with VPN connected"

    # ==================== NITTER OPERATIONS ====================

    def list_nitters(self) -> list[dict]:
        """List all Nitter containers."""
        cmd = "docker ps -a --filter 'name=nitter' --format '{{.Names}}|{{.Status}}|{{.Ports}}'"
        stdout, _, _ = self.run_command(cmd)
        nitters = []
        for line in stdout.strip().split('\n'):
            if line and 'redis' not in line.lower():
                parts = line.split('|')
                nitters.append({
                    "name": parts[0],
                    "status": parts[1] if len(parts) > 1 else "unknown",
                    "ports": parts[2] if len(parts) > 2 else ""
                })
        return nitters

    def restart_nitter(self, nitter_id: str) -> tuple[bool, str]:
        """Restart a Nitter container."""
        cmd = f"docker restart nitter-{nitter_id}"
        stdout, stderr, code = self.run_command(cmd)
        return code == 0, stdout or stderr

    def flush_nitter_cache(self, nitter_id: str) -> tuple[bool, str]:
        """Flush the Redis cache for a Nitter instance."""
        cmd = f"docker exec nitter-redis-{nitter_id} redis-cli FLUSHALL"
        stdout, stderr, code = self.run_command(cmd)
        return code == 0, stdout or stderr

    # ==================== SESSION OPERATIONS ====================

    def get_sessions(self) -> str:
        """Get current sessions.jsonl content."""
        cmd = f"cat {self.project_path}/sessions.jsonl"
        stdout, _, _ = self.run_command(cmd)
        return stdout

    def update_sessions(self, sessions_content: str) -> tuple[bool, str]:
        """Update sessions.jsonl and restart all Nitters."""
        # Write new sessions
        escaped = sessions_content.replace("'", "'\\''")
        cmd = f"echo '{escaped}' > {self.project_path}/sessions.jsonl"
        _, stderr, code = self.run_command(cmd)
        if code != 0:
            return False, stderr
        
        # Restart all Nitter containers
        cmd = "docker ps --filter 'name=nitter' --format '{{.Names}}' | grep -v redis | xargs -r docker restart"
        stdout, stderr, code = self.run_command(cmd)
        return True, "Sessions updated and Nitters restarted"

    def refresh_sessions_from_cookies(self) -> tuple[bool, str]:
        """Run the cookie scraper to refresh sessions."""
        cmd = f"cd {self.project_path} && source venv/bin/activate && python -c 'from app.scraper_cookies import get_nitter_sessions; print(get_nitter_sessions())'"
        stdout, stderr, code = self.run_command(cmd)
        return code == 0, stdout or stderr

    # ==================== HEALTH MONITORING ====================

    def get_all_containers(self) -> list[dict]:
        """Get status of all project containers."""
        cmd = "docker ps -a --filter 'network=project-hyperdrive_default' --format '{{.Names}}|{{.Status}}|{{.Ports}}'"
        stdout, _, _ = self.run_command(cmd)
        containers = []
        for line in stdout.strip().split('\n'):
            if line:
                parts = line.split('|')
                name = parts[0]
                status = parts[1] if len(parts) > 1 else "unknown"
                containers.append({
                    "name": name,
                    "status": status,
                    "healthy": "healthy" in status.lower() or "up" in status.lower(),
                    "ports": parts[2] if len(parts) > 2 else ""
                })
        return containers

    def get_redis_queue_stats(self) -> dict:
        """Get job queue statistics."""
        cmd = "docker exec redis-queue redis-cli LLEN hyperdrive:jobs:pending"
        pending, _, _ = self.run_command(cmd)
        
        cmd = "docker exec redis-queue redis-cli HLEN hyperdrive:jobs"
        total, _, _ = self.run_command(cmd)
        
        cmd = "docker exec redis-queue redis-cli HGETALL hyperdrive:workers"
        workers_raw, _, _ = self.run_command(cmd)
        
        return {
            "pending_jobs": int(pending.strip()) if pending.strip().isdigit() else 0,
            "total_jobs": int(total.strip()) if total.strip().isdigit() else 0,
            "workers_raw": workers_raw
        }

    def get_disk_usage(self) -> str:
        """Get disk usage on VPS."""
        cmd = "df -h / | tail -1"
        stdout, _, _ = self.run_command(cmd)
        return stdout.strip()

    def get_memory_usage(self) -> str:
        """Get memory usage on VPS."""
        cmd = "free -h | grep Mem"
        stdout, _, _ = self.run_command(cmd)
        return stdout.strip()

    def close(self):
        """Close SSH connection."""
        if self._client:
            self._client.close()
            self._client = None

