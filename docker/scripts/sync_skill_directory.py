#!/usr/bin/env python3
"""
Skills Directory Migration Script for v2.2.0 upgrade.

This script migrates skills from the legacy flat directory structure to
tenant-isolated directories.

Migration:
    FROM: ${ROOT_DIR}/skills/ (flat directory, skills directly under skills/)
    TO:   ${ROOT_DIR}/skills/{tenant_id}/

The tenant_id is determined by querying user_tenant_t for the first record
where user_role = 'ADMIN'.

Usage (run on host machine):
    python sync_skill_directory.py [--dry-run]

Options:
    --dry-run: Show what would be migrated without making changes
    --verbose: Enable verbose debug output
"""

import os
import sys
import argparse
import logging
import shutil
import subprocess
import base64
import tempfile
from pathlib import Path
from typing import Optional

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Constants
CONTAINER_NAME = "nexent-config"
DEFAULT_TENANT_ID = "tenant_id"


def get_env(key: str, default: str = "") -> str:
    """Get environment variable with optional default."""
    return os.environ.get(key, default)


def load_environment_from_host():
    """
    Load environment variables from host .env file.
    Looks for .env in the same directory as this script's parent (docker/).
    """
    script_dir = Path(__file__).resolve().parent
    docker_dir = script_dir.parent
    env_file = docker_dir / ".env"

    if env_file.is_file():
        logger.info(f"Loading environment from: {env_file}")
        with open(env_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, _, value = line.partition('=')
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    if key and key not in os.environ:
                        os.environ[key] = value
        return True
    else:
        logger.warning(f".env file not found at: {env_file}")
        logger.info("Will use existing environment variables or defaults")
        return False


def get_root_dir() -> str:
    """Get ROOT_DIR from environment, normalized for the current OS."""
    root_dir = get_env("ROOT_DIR")
    if not root_dir:
        script_dir = Path(__file__).resolve().parent
        docker_dir = script_dir.parent
        env_file = docker_dir / ".env"
        if env_file.is_file():
            with open(env_file, 'r') as f:
                for line in f:
                    if line.startswith("ROOT_DIR="):
                        root_dir = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break

    # Normalize path separators for current OS
    if root_dir:
        root_dir = str(Path(root_dir))
    return root_dir


def check_container_running():
    """Check if nexent-config container is running."""
    try:
        result = subprocess.run(
            ['docker', 'ps', '--format', '{{.Names}}'],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0:
            containers = result.stdout.strip().split('\n')
            if CONTAINER_NAME in containers:
                logger.info(f"Container '{CONTAINER_NAME}' is running")
                return True
            else:
                logger.error(f"Container '{CONTAINER_NAME}' is not running")
                logger.info("Please start the containers with: cd docker && docker compose up -d")
                return False
        else:
            logger.error("Could not query Docker containers")
            return False
    except FileNotFoundError:
        logger.error("Docker not available on this system")
        return False
    except Exception as e:
        logger.error(f"Error checking Docker containers: {e}")
        return False


def exec_python_in_container(python_code: str) -> tuple:
    """
    Execute Python code inside the container using base64 encoding.

    This approach avoids shell escaping issues by encoding the Python code
    as base64 and decoding it inside the container.

    Args:
        python_code: Python code to execute inside the container

    Returns:
        Tuple of (return_code, stdout, stderr)
    """
    # Encode Python code as base64
    encoded = base64.b64encode(python_code.encode('utf-8')).decode('ascii')

    # Create the shell command that decodes and executes the Python code
    shell_cmd = f'python3 -c "import base64, sys; exec(base64.b64decode(sys.stdin.read()).decode(\'utf-8\'))"'

    try:
        # Use stdin for the base64 data
        full_cmd = ['docker', 'exec', '-i', CONTAINER_NAME, 'sh', '-c', shell_cmd]
        result = subprocess.run(
            full_cmd,
            input=encoded,
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        logger.error("Command timed out")
        return -1, "", "Command timed out"
    except Exception as e:
        logger.error(f"Failed to execute command in container: {e}")
        return -1, "", str(e)


def test_postgres_connection_in_container() -> bool:
    """
    Test PostgreSQL connection from inside the container using Python.

    Returns:
        True if connection successful, False otherwise
    """
    logger.info("Testing PostgreSQL connection from inside container...")

    python_code = '''
import os
import sys
try:
    import psycopg2
    conn = psycopg2.connect(
        host=os.getenv('POSTGRES_HOST', 'nexent-postgresql'),
        port=os.getenv('POSTGRES_PORT', '5432'),
        database=os.getenv('POSTGRES_DB', 'nexent'),
        user=os.getenv('POSTGRES_USER', 'nexent'),
        password=os.getenv('NEXENT_POSTGRES_PASSWORD', '')
    )
    conn.close()
    print("Connection successful")
    sys.exit(0)
except Exception as e:
    print(f"Connection failed: {e}", file=sys.stderr)
    sys.exit(1)
'''

    returncode, stdout, stderr = exec_python_in_container(python_code)

    if returncode == 0:
        logger.info("PostgreSQL connection test: SUCCESS")
        return True
    else:
        logger.warning(f"PostgreSQL connection test failed: {stderr.strip()}")
        return False


def get_admin_tenant_id_in_container() -> Optional[str]:
    """
    Get tenant_id from the first user_tenant_t record where user_role = 'ADMIN'.

    Executes the query inside the container using Python.

    Returns:
        tenant_id string or None if not found
    """
    logger.info("Querying admin tenant_id from inside container...")

    python_code = '''
import os
import sys

try:
    import psycopg2

    conn = psycopg2.connect(
        host=os.getenv('POSTGRES_HOST', 'nexent-postgresql'),
        port=os.getenv('POSTGRES_PORT', '5432'),
        database=os.getenv('POSTGRES_DB', 'nexent'),
        user=os.getenv('POSTGRES_USER', 'nexent'),
        password=os.getenv('NEXENT_POSTGRES_PASSWORD', '')
    )

    cur = conn.cursor()
    cur.execute("""
        SELECT tenant_id
        FROM nexent.user_tenant_t
        WHERE user_role = 'ADMIN'
          AND delete_flag = 'N'
          AND tenant_id IS NOT NULL
          AND tenant_id != ''
        ORDER BY user_tenant_id ASC
        LIMIT 1
    """)

    result = cur.fetchone()
    cur.close()
    conn.close()

    if result:
        print(result[0])
        sys.exit(0)
    else:
        print("No ADMIN user found", file=sys.stderr)
        sys.exit(1)

except Exception as e:
    print(f"Query failed: {e}", file=sys.stderr)
    sys.exit(1)
'''

    returncode, stdout, stderr = exec_python_in_container(python_code)

    if returncode == 0:
        tenant_id = stdout.strip()
        if tenant_id:
            logger.info(f"Found ADMIN tenant_id: {tenant_id}")
            return tenant_id
        else:
            logger.warning("No user with user_role='ADMIN' found in user_tenant_t")
            return None
    else:
        logger.error(f"Failed to query admin tenant_id: {stderr.strip()}")
        return None


def discover_legacy_skills_dir(root_dir: str) -> str:
    """
    Discover the legacy skills directory.

    The legacy skills are located in the old nexent folder (sibling to nexent-data).
    The new skills base is under {root_dir}/skills/{tenant_id}.

    Legacy path: {root_dir}/../nexent/skills (old nexent folder)
    New base:    {root_dir}/skills

    Returns:
        Path to the legacy skills directory (normalized for current OS)
    """
    candidates = []
    if root_dir:
        # Legacy path FIRST: check old nexent folder (nexent-data's sibling)
        # This is the actual source of legacy skills
        root_path = Path(root_dir)
        legacy_candidate = root_path.parent / "nexent" / "skills"
        candidates.append(str(legacy_candidate))
        # New base path (NOT the legacy, this is the destination base)
        candidates.append(str(Path(root_dir) / "skills"))
    candidates.append("skills")
    candidates.append("./skills")

    for candidate in candidates:
        if Path(candidate).is_dir():
            logger.info(f"Found legacy skills directory: {candidate}")
            return candidate

    logger.warning("Could not find legacy skills directory")
    return candidates[0] if candidates[0] else "skills"


def discover_skill_directories(skills_path: str) -> list:
    """
    List all skill directories under the given base path.

    A valid skill directory contains at least a SKILL.md file.

    Args:
        skills_path: Base skills directory path

    Returns:
        List of skill directory names (not full paths)
    """
    skills_path_obj = Path(skills_path)
    if not skills_path_obj.is_dir():
        logger.warning(f"Skills directory does not exist: {skills_path}")
        return []

    skills = []
    try:
        for item in skills_path_obj.iterdir():
            if item.is_dir():
                if (item / "SKILL.md").is_file():
                    skills.append(item.name)
                else:
                    logger.debug(f"Skipping non-skill directory: {item.name}")
    except Exception as e:
        logger.error(f"Error listing skills directory: {e}")

    return skills


def validate_skill_directory(skill_dir: str) -> dict:
    """
    Validate a skill directory structure.

    Args:
        skill_dir: Path to the skill directory

    Returns:
        Dict with validation results
    """
    skill_dir_obj = Path(skill_dir)
    result = {
        "is_valid": True,
        "skill_name": skill_dir_obj.name,
        "files": [],
        "errors": []
    }

    if not skill_dir_obj.is_dir():
        result["is_valid"] = False
        result["errors"].append("Directory does not exist")
        return result

    skill_md = skill_dir_obj / "SKILL.md"
    if not skill_md.is_file():
        result["is_valid"] = False
        result["errors"].append("SKILL.md not found")

    try:
        for item in skill_dir_obj.rglob('*'):
            if item.is_file():
                rel_path = item.relative_to(skill_dir_obj)
                result["files"].append(str(rel_path))
    except Exception as e:
        result["errors"].append(f"Error scanning files: {e}")

    return result


def migrate_skills(
    legacy_dir: str,
    target_dir: str,
    skills: list,
    dry_run: bool = False
) -> dict:
    """
    Migrate skills from legacy directory to target directory.

    Args:
        legacy_dir: Source directory path (host path)
        target_dir: Target directory path (host path)
        skills: List of skill names to migrate
        dry_run: If True, only show what would be done

    Returns:
        Migration results dict
    """
    results = {
        "total": len(skills),
        "migrated": 0,
        "skipped": 0,
        "failed": 0,
        "details": []
    }

    legacy_dir_obj = Path(legacy_dir)
    target_dir_obj = Path(target_dir)

    for skill_name in skills:
        source = legacy_dir_obj / skill_name
        target = target_dir_obj / skill_name

        logger.info(f"Processing skill: {skill_name}")

        validation = validate_skill_directory(str(source))
        if not validation["is_valid"]:
            logger.warning(f"  Invalid skill directory: {', '.join(validation['errors'])}")
            results["skipped"] += 1
            results["details"].append({
                "skill": skill_name,
                "status": "skipped",
                "reason": f"Validation failed: {', '.join(validation['errors'])}"
            })
            continue

        if target.exists():
            logger.info(f"  Target already exists, skipping: {target}")
            results["skipped"] += 1
            results["details"].append({
                "skill": skill_name,
                "status": "skipped",
                "reason": "Already exists in target directory"
            })
            continue

        if dry_run:
            logger.info(f"  [DRY-RUN] Would migrate to: {target}")
            logger.info(f"  Files: {', '.join(validation['files'])}")
            results["migrated"] += 1
            results["details"].append({
                "skill": skill_name,
                "status": "dry-run",
                "source": str(source),
                "target": str(target),
                "files_count": len(validation["files"])
            })
        else:
            try:
                target.mkdir(parents=True, exist_ok=True)

                for item in source.rglob('*'):
                    if item.is_file():
                        rel_path = item.relative_to(source)
                        dst_file = target / rel_path
                        dst_file.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(item, dst_file)

                logger.info(f"  Migrated successfully: {len(validation['files'])} files")
                results["migrated"] += 1
                results["details"].append({
                    "skill": skill_name,
                    "status": "success",
                    "source": str(source),
                    "target": str(target),
                    "files_count": len(validation["files"])
                })

            except Exception as e:
                logger.error(f"  Failed to migrate: {e}")
                results["failed"] += 1
                results["details"].append({
                    "skill": skill_name,
                    "status": "failed",
                    "reason": str(e)
                })

    return results


def print_results(results: dict):
    """Print migration results summary."""
    logger.info("=" * 60)
    logger.info("Migration Results:")
    logger.info(f"  Total skills found: {results['total']}")
    logger.info(f"  Migrated: {results['migrated']}")
    logger.info(f"  Skipped: {results['skipped']}")
    logger.info(f"  Failed: {results['failed']}")
    logger.info("=" * 60)

    if results['details']:
        logger.info("\nDetails:")
        for detail in results['details']:
            status = detail['status']
            skill = detail['skill']
            if status == 'success':
                logger.info(f"  [OK] {skill}: {detail.get('files_count', 0)} files -> {detail.get('target', 'N/A')}")
            elif status == 'dry-run':
                logger.info(f"  [DRY-RUN] {skill}: would migrate {detail.get('files_count', 0)} files to {detail.get('target', 'N/A')}")
            elif status == 'skipped':
                logger.info(f"  [SKIP] {skill}: {detail.get('reason', 'unknown reason')}")
            else:
                logger.info(f"  [FAIL] {skill}: {detail.get('reason', 'unknown error')}")


def main():
    """Main function."""
    parser = argparse.ArgumentParser(
        description='Migrate skills directory for v2.2.0 upgrade (run on host)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be migrated without making changes'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose debug output'
    )
    parser.add_argument(
        '--legacy-dir',
        type=str,
        default=None,
        help='Override legacy skills directory path (host path)'
    )
    parser.add_argument(
        '--target-dir',
        type=str,
        default=None,
        help='Override target skills directory path (host path)'
    )
    parser.add_argument(
        '--skip-db',
        action='store_true',
        help='Skip database connection and use existing tenant directories'
    )
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    logger.info("=" * 60)
    logger.info("Skills Directory Migration Script (v2.2.0)")
    logger.info("=" * 60)

    if args.dry_run:
        logger.info("Mode: DRY-RUN (no changes will be made)")

    # Step 1: Load environment from .env file
    logger.info("\n[Step 1/6] Loading environment variables...")
    load_environment_from_host()

    # Get ROOT_DIR
    root_dir = get_root_dir()
    if root_dir:
        logger.info(f"  ROOT_DIR: {root_dir}")
    else:
        logger.warning("  ROOT_DIR not set, using current directory")

    # Determine host paths
    skills_base = str(Path(root_dir) / "skills") if root_dir else "skills"

    # Step 2: Check if container is running
    logger.info("\n[Step 2/6] Checking container status...")
    container_running = check_container_running()
    if not container_running:
        logger.error("nexent-config container is not running")
        sys.exit(1)

    # Step 3: Test PostgreSQL connection and get tenant_id from container
    tenant_id = None
    if not args.skip_db:
        logger.info("\n[Step 3/6] Testing PostgreSQL connection from inside container...")

        if test_postgres_connection_in_container():
            logger.info("\n[Step 4/6] Querying admin tenant_id...")
            tenant_id = get_admin_tenant_id_in_container()

            if not tenant_id:
                logger.warning("Could not determine tenant_id from database")
        else:
            logger.warning("Could not connect to PostgreSQL")
    else:
        logger.info("\n[Step 3/6] Skipping database connection (--skip-db)")

    # Fallback: check existing tenant directories on host
    if not tenant_id:
        logger.info("Checking for existing tenant directories...")
        skills_base_obj = Path(skills_base)
        if skills_base_obj.is_dir():
            existing_tenants = [
                d.name for d in skills_base_obj.iterdir()
                if d.is_dir() and d.name not in ['.', '..']
            ]
            if existing_tenants:
                tenant_id = existing_tenants[0]
                logger.info(f"Using existing tenant directory: {tenant_id}")

    # Step 5: Determine directories
    legacy_dir = args.legacy_dir or discover_legacy_skills_dir(root_dir or ".")
    logger.info(f"\n[Step 5/6] Migration paths:")
    logger.info(f"  Legacy directory (host): {legacy_dir}")
    logger.info(f"  Skills base (host): {skills_base}")

    if args.target_dir:
        target_base = args.target_dir
        logger.info(f"  Target directory (host): {target_base}")
    elif tenant_id:
        target_base = str(Path(skills_base) / tenant_id)
        logger.info(f"  Target directory (host): {target_base}")
    else:
        logger.error("Cannot determine target directory: no tenant_id found")
        logger.info("Options:")
        logger.info("  1. Ensure user_tenant_t has at least one ADMIN user")
        logger.info("  2. Provide --target-dir explicitly")
        logger.info("  3. Use --skip-db and ensure existing tenant directories exist")
        sys.exit(1)

    # Step 6: Discover and migrate skills
    logger.info("\n[Step 6/6] Discovering skills in legacy directory...")

    if not Path(legacy_dir).is_dir():
        logger.warning(f"Legacy directory does not exist: {legacy_dir}")
        logger.info("No migration needed (source directory not found)")
        return

    skills = discover_skill_directories(legacy_dir)
    if not skills:
        logger.info("No skills found in legacy directory")
        logger.info("Migration complete (nothing to migrate)")
        return

    logger.info(f"Found {len(skills)} skill(s): {', '.join(skills)}")

    # Execute migration
    results = migrate_skills(
        legacy_dir=legacy_dir,
        target_dir=target_base,
        skills=skills,
        dry_run=args.dry_run
    )

    print_results(results)

    # Final summary
    logger.info("\n" + "=" * 60)
    if args.dry_run:
        logger.info("DRY-RUN complete. To apply migration, run without --dry-run")
    else:
        logger.info("Migration completed")
        if results['migrated'] > 0:
            logger.info(f"\nSuccessfully migrated {results['migrated']} skill(s)")
            logger.info(f"Skills are now available at: {target_base}")
            logger.info("\nNote: The legacy directory has been preserved.")
            logger.info("You can remove it manually after verifying the migration:")
            logger.info(f"  rm -rf {legacy_dir}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
