#!/usr/bin/env python3
"""
start_services.py

This script starts the Supabase stack and the local AI stack together
as a unified Docker Compose project.
"""

import os
import subprocess
import shutil
import time
import argparse
import platform
import sys

def run_command(cmd, cwd=None):
    """Run a shell command and print it."""
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, check=True)

def clone_supabase_repo():
    """Clone the Supabase repository using sparse checkout if not already present."""
    if not os.path.exists("supabase"):
        print("Cloning the Supabase repository...")
        run_command([
            "git", "clone", "--filter=blob:none", "--no-checkout",
            "https://github.com/supabase/supabase.git"
        ])
        os.chdir("supabase")
        run_command(["git", "sparse-checkout", "init", "--cone"])
        run_command(["git", "sparse-checkout", "set", "docker"])
        run_command(["git", "checkout", "master"])
        os.chdir("..")
    else:
        print("Supabase repository already exists, updating...")
        os.chdir("supabase")
        run_command(["git", "pull"])
        os.chdir("..")

def prepare_supabase_env():
    """Copy .env to .env in supabase/docker."""
    env_path = os.path.join("supabase", "docker", ".env")
    env_example_path = os.path.join(".env")
    print("Copying .env in root to .env in supabase/docker...")
    shutil.copyfile(env_example_path, env_path)

def stop_existing_containers(profile=None, environment=None):
    """Stop and remove all containers for the unified project 'localai'."""
    print("Stopping and removing existing containers for the unified project 'localai'...")

    # [수정] 모든 프로필의 컨테이너를 제거하기 위해 여러 번 down 실행
    # 이렇게 하면 이전에 다른 프로필로 실행된 컨테이너도 제거됩니다
    profiles_to_clean = ["cpu", "gpu-nvidia", "gpu-amd"]

    for prof in profiles_to_clean:
        cmd = ["docker", "compose", "-p", "localai", "--profile", prof]
        cmd.extend(["-f", "docker-compose.yml"])
        if environment and environment == "private":
            cmd.extend(["-f", "docker-compose.override.private.yml"])
        if environment and environment == "public":
            cmd.extend(["-f", "docker-compose.override.public.yml"])
            cmd.extend(["-f", "docker-compose.override.public.supabase.yml"])
        cmd.extend(["down"])

        # 에러가 발생해도 계속 진행 (해당 프로필의 컨테이너가 없을 수 있음)
        try:
            run_command(cmd)
        except subprocess.CalledProcessError:
            print(f"Note: No containers found for profile '{prof}' or already removed")

    # 프로필이 지정되지 않은 서비스들도 제거
    cmd = ["docker", "compose", "-p", "localai"]
    cmd.extend(["-f", "docker-compose.yml"])
    if environment and environment == "private":
        cmd.extend(["-f", "docker-compose.override.private.yml"])
    if environment and environment == "public":
        cmd.extend(["-f", "docker-compose.override.public.yml"])
        cmd.extend(["-f", "docker-compose.override.public.supabase.yml"])
    cmd.extend(["down"])

    try:
        run_command(cmd)
    except subprocess.CalledProcessError:
        print("Note: No containers found without profile or already removed")

# [수정] 'start_local_ai' 함수를 'start_services'로 변경하고 모든 파일을 포함
def start_services(profile=None, environment=None):
    """Start all services (Local AI and Supabase) using the main compose file."""
    print("Starting all services (Local AI and Supabase)...")
    cmd = ["docker", "compose", "-p", "localai"]
    if profile and profile != "none":
        cmd.extend(["--profile", profile])

    # 메인 파일은 'include'를 통해 Supabase를 자동으로 불러옴
    cmd.extend(["-f", "docker-compose.yml"])

    # 환경별 오버라이드 파일 추가
    if environment and environment == "private":
        cmd.extend(["-f", "docker-compose.override.private.yml"])
    if environment and environment == "public":
        cmd.extend(["-f", "docker-compose.override.public.yml"])
        # Supabase 공개 오버라이드 파일 추가
        cmd.extend(["-f", "docker-compose.override.public.supabase.yml"])

    cmd.extend(["up", "-d"])

    # Run the command but don't fail if n8n-import fails
    try:
        run_command(cmd)
    except subprocess.CalledProcessError as e:
        print(f"Warning: Some services may have failed to start (exit code {e.returncode})")
        print("Checking if main services are running...")

        # Start n8n manually if it exists but is not running
        try:
            check_cmd = ["docker", "ps", "-a", "--filter", "name=n8n", "--format", "{{.Names}} {{.Status}}"]
            result = subprocess.run(check_cmd, capture_output=True, text=True, check=True)
            for line in result.stdout.strip().split('\n'):
                if line and 'n8n' in line and 'Created' in line:
                    print("Starting n8n container manually...")
                    subprocess.run(["docker", "start", "n8n"], check=True)
        except Exception as start_error:
            print(f"Note: Could not auto-start n8n: {start_error}")

def generate_searxng_secret_key():
    """Generate a secret key for SearXNG based on the current platform."""
    print("Checking SearXNG settings...")

    # Define paths for SearXNG settings files
    settings_path = os.path.join("searxng", "settings.yml")
    settings_base_path = os.path.join("searxng", "settings-base.yml")

    # Check if settings-base.yml exists
    if not os.path.exists(settings_base_path):
        print(f"Warning: SearXNG base settings file not found at {settings_base_path}")
        return

    # Check if settings.yml exists, if not create it from settings-base.yml
    if not os.path.exists(settings_path):
        print(f"SearXNG settings.yml not found. Creating from {settings_base_path}...")
        try:
            shutil.copyfile(settings_base_path, settings_path)
            print(f"Created {settings_path} from {settings_base_path}")
        except Exception as e:
            print(f"Error creating settings.yml: {e}")
            return
    else:
        print(f"SearXNG settings.yml already exists at {settings_path}")

    # Check if secret key is already set (not 'ultrasecretkey')
    try:
        with open(settings_path, 'r') as f:
            content = f.read()
            if 'ultrasecretkey' not in content:
                print("SearXNG secret key already configured. Skipping generation.")
                return
    except Exception as e:
        print(f"Error reading settings file: {e}")

    print("Generating SearXNG secret key...")

    # Detect the platform and run the appropriate command
    system = platform.system()

    try:
        if system == "Windows":
            print("Detected Windows platform, using PowerShell to generate secret key...")
            # PowerShell command to generate a random key and replace in the settings file
            ps_command = [
                "powershell", "-Command",
                "$randomBytes = New-Object byte[] 32; " +
                "(New-Object Security.Cryptography.RNGCryptoServiceProvider).GetBytes($randomBytes); " +
                "$secretKey = -join ($randomBytes | ForEach-Object { \"{0:x2}\" -f $_ }); " +
                "(Get-Content searxng/settings.yml) -replace 'ultrasecretkey', $secretKey | Set-Content searxng/settings.yml"
            ]
            subprocess.run(ps_command, check=True)

        elif system == "Darwin":  # macOS
            print("Detected macOS platform, using sed command with empty string parameter...")
            # macOS sed command requires an empty string for the -i parameter
            openssl_cmd = ["openssl", "rand", "-hex", "32"]
            random_key = subprocess.check_output(openssl_cmd).decode('utf-8').strip()
            sed_cmd = ["sed", "-i", "", f"s|ultrasecretkey|{random_key}|g", settings_path]
            subprocess.run(sed_cmd, check=True)

        else:  # Linux and other Unix-like systems
            print("Detected Linux/Unix platform, using standard sed command...")
            # Standard sed command for Linux
            openssl_cmd = ["openssl", "rand", "-hex", "32"]
            random_key = subprocess.check_output(openssl_cmd).decode('utf-8').strip()
            sed_cmd = ["sed", "-i", f"s|ultrasecretkey|{random_key}|g", settings_path]
            subprocess.run(sed_cmd, check=True)

        print("SearXNG secret key generated successfully.")

    except Exception as e:
        print(f"Error generating SearXNG secret key: {e}")
        print("You may need to manually generate the secret key using the commands:")
        print("  - Linux: sed -i \"s|ultrasecretkey|$(openssl rand -hex 32)|g\" searxng/settings.yml")
        print("  - macOS: sed -i '' \"s|ultrasecretkey|$(openssl rand -hex 32)|g\" searxng/settings.yml")
        print("  - Windows (PowerShell):")
        print("    $randomBytes = New-Object byte[] 32")
        print("    (New-Object Security.Cryptography.RNGCryptoServiceProvider).GetBytes($randomBytes)")
        print("    $secretKey = -join ($randomBytes | ForEach-Object { \"{0:x2}\" -f $_ })")
        print("    (Get-Content searxng/settings.yml) -replace 'ultrasecretkey', $secretKey | Set-Content searxng/settings.yml")

def check_and_fix_docker_compose_for_searxng():
    """Check and modify docker-compose.yml for SearXNG first run."""
    docker_compose_path = "docker-compose.yml"
    if not os.path.exists(docker_compose_path):
        print(f"Warning: Docker Compose file not found at {docker_compose_path}")
        return

    try:
        # Read the docker-compose.yml file
        with open(docker_compose_path, 'r') as file:
            content = file.read()

        # Default to first run
        is_first_run = True

        # Check if Docker is running and if the SearXNG container exists
        try:
            # Check if the SearXNG container is running
            container_check = subprocess.run(
                ["docker", "ps", "--filter", "name=searxng", "--format", "{{.Names}}"],
                capture_output=True, text=True, check=True
            )
            searxng_containers = container_check.stdout.strip().split('\n')

            # If SearXNG container is running, check inside for uwsgi.ini
            if any(container for container in searxng_containers if container):
                container_name = next(container for container in searxng_containers if container)
                print(f"Found running SearXNG container: {container_name}")

                # Check if uwsgi.ini exists inside the container
                container_check = subprocess.run(
                    ["docker", "exec", container_name, "sh", "-c", "[ -f /etc/searxng/uwsgi.ini ] && echo 'found' || echo 'not_found'"],
                    capture_output=True, text=True, check=False
                )

                if "found" in container_check.stdout:
                    print("Found uwsgi.ini inside the SearXNG container - not first run")
                    is_first_run = False
                else:
                    print("uwsgi.ini not found inside the SearXNG container - first run")
                    is_first_run = True
            else:
                print("No running SearXNG container found - assuming first run")
        except Exception as e:
            print(f"Error checking Docker container: {e} - assuming first run")

        if is_first_run and "cap_drop: - ALL" in content:
            print("First run detected for SearXNG. Temporarily removing 'cap_drop: - ALL' directive...")
            # Temporarily comment out the cap_drop line
            modified_content = content.replace("cap_drop: - ALL", "# cap_drop: - ALL  # Temporarily commented out for first run")

            # Write the modified content back
            with open(docker_compose_path, 'w') as file:
                file.write(modified_content)

            print("Note: After the first run completes successfully, you should re-add 'cap_drop: - ALL' to docker-compose.yml for security reasons.")
        elif not is_first_run and "# cap_drop: - ALL  # Temporarily commented out for first run" in content:
            print("SearXNG has been initialized. Re-enabling 'cap_drop: - ALL' directive for security...")
            # Uncomment the cap_drop line
            modified_content = content.replace("# cap_drop: - ALL  # Temporarily commented out for first run", "cap_drop: - ALL")

            # Write the modified content back
            with open(docker_compose_path, 'w') as file:
                file.write(modified_content)

    except Exception as e:
        print(f"Error checking/modifying docker-compose.yml for SearXNG: {e}")

def main():
    parser = argparse.ArgumentParser(description='Start the local AI and Supabase services.')
    parser.add_argument('--profile', choices=['cpu', 'gpu-nvidia', 'gpu-amd', 'none'], default='cpu',
                        help='Profile to use for Docker Compose (default: cpu)')
    parser.add_argument('--environment', choices=['private', 'public'], default='private',
                        help='Environment to use for Docker Compose (default: private)')
    args = parser.parse_args()

    clone_supabase_repo()
    prepare_supabase_env()

    # Generate SearXNG secret key and check docker-compose.yml
    generate_searxng_secret_key()
    check_and_fix_docker_compose_for_searxng()

    # [수정] 'stop' 함수에도 environment 전달
    stop_existing_containers(args.profile, args.environment)

    # [수정] 'start_supabase' 및 'time.sleep' 호출 삭제
    # 'start_services'가 Supabase를 포함하여 모든 것을 시작합니다.
    # Docker Compose의 'depends_on'이 시작 순서를 관리합니다.
    
    # [수정] 'start_local_ai' 대신 통합된 'start_services' 호출
    start_services(args.profile, args.environment)
    
    print("\nAll services started successfully!")

if __name__ == "__main__":
    main()