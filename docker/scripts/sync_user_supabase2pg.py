#!/usr/bin/env python3
"""
Update user data script for v1.8.0 upgrade.
This script updates user_email and user_role in the user_tenant_t table.

Usage (run inside nexent-config container):
    python sync_user_supabase2pg.py [--dry-run]

Options:
    --dry-run: Show what would be updated without making changes
    --verbose: Enable verbose debug output

Environment variables are loaded from Docker container environment.
"""

import os
import sys
import argparse
import logging
import requests

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Constants
DEFAULT_TENANT_ID = "tenant_id"
DEFAULT_USER_ID = "user_id"
LEGACY_ADMIN_EMAIL = "nexent@example.com"


def check_docker_containers():
    """Check if required Docker containers are running"""
    try:
        import subprocess
        result = subprocess.run(
            ['docker', 'ps', '--format', '{{.Names}}'],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0:
            containers = result.stdout.strip().split('\n')
            logger.info(f"Running containers: {containers}")

            required_containers = ['nexent-postgresql']
            missing = [c for c in required_containers if c not in containers]

            if missing:
                logger.warning(f"Missing required containers: {missing}")
                logger.info("Please ensure Docker containers are running with: docker compose up -d")
                return False

            return True
        else:
            logger.warning("Could not query Docker containers")
            return None
    except FileNotFoundError:
        logger.warning("Docker not available on this system")
        return None
    except Exception as e:
        logger.warning(f"Error checking Docker containers: {e}")
        return None


def test_connection_with_psql(conn_params):
    """Test connection using psql command if available"""
    try:
        import subprocess

        password = conn_params.get('password', '')
        env = os.environ.copy()

        cmd = [
            'psql',
            '-h', conn_params.get('host', 'localhost'),
            '-p', str(conn_params.get('port', 5434)),
            '-U', conn_params.get('user', 'nexent'),
            '-d', conn_params.get('database', 'nexent'),
            '-c', 'SELECT 1;'
        ]

        if password:
            env['PGPASSWORD'] = password

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10,
            env=env
        )

        if result.returncode == 0:
            logger.info("psql connection test: SUCCESS")
            return True
        else:
            logger.warning(f"psql connection test failed: {result.stderr}")
            return False
    except FileNotFoundError:
        logger.debug("psql not available, skipping command-line test")
        return None
    except Exception as e:
        logger.debug(f"psql test error: {e}")
        return None


def load_environment_from_container():
    """
    Validate and display environment variables from container environment.
    Environment variables are already set by Docker via env_file directive.
    """
    required_vars = [
        'POSTGRES_DB',
        'POSTGRES_USER',
        'NEXENT_POSTGRES_PASSWORD',
        'POSTGRES_HOST',
        'POSTGRES_PORT',
        'SERVICE_ROLE_KEY'
    ]

    missing = [var for var in required_vars if not os.getenv(var)]
    if missing:
        logger.error(f"Missing required environment variables: {missing}")
        return False

    logger.info("Environment variables loaded from container")
    return True


def get_postgres_connection_params():
    """Get PostgreSQL connection parameters from environment"""
    # Validate environment variables are set
    load_environment_from_container()

    # Default port for docker-compose is 5434
    params = {
        'host': os.getenv('POSTGRES_HOST', '127.0.0.1'),
        'port': os.getenv('POSTGRES_PORT', '5434'),
        'database': os.getenv('POSTGRES_DB', 'nexent'),
        'user': os.getenv('POSTGRES_USER', 'nexent'),
        'password': os.getenv('NEXENT_POSTGRES_PASSWORD', '')
    }

    logger.info("Database connection parameters:")
    logger.info(f"  Host: {params['host']}")
    logger.info(f"  Port: {params['port']}")
    logger.info(f"  Database: {params['database']}")
    logger.info(f"  User: {params['user']}")
    logger.info(f"  Password: {'*' * len(params['password']) if params['password'] else '(empty)'}")

    return params


def get_supabase_params():
    """Get Supabase connection parameters from environment"""
    service_role_key = os.getenv('SERVICE_ROLE_KEY', '')
    service_role_key = service_role_key.strip('"').strip("'")

    supabase_url = os.getenv('SUPABASE_URL', 'http://127.0.0.1:8000')

    params = {
        'url': supabase_url,
        'key': service_role_key
    }

    if not params['key']:
        logger.warning("SERVICE_ROLE_KEY is not set")

    return params


def get_db_connection(conn_params):
    """Get database connection"""
    import psycopg2
    try:
        # First test basic connectivity
        logger.info(f"Attempting to connect to PostgreSQL at {conn_params.get('host')}:{conn_params.get('port')}...")
        conn = psycopg2.connect(**conn_params)
        logger.info("Database connection established successfully")
        return conn
    except psycopg2.OperationalError as e:
        logger.error(f"Database connection failed: {e}")
        logger.error("Please check:")
        logger.error("  1. PostgreSQL is running")
        logger.error("  2. Host/port configuration is correct")
        logger.error("  3. Credentials are correct")
        logger.error("  4. Network is accessible")
        return None
    except Exception as e:
        logger.error(f"Unexpected database error: {e}")
        return None


def fetch_all_user_tenant_records(conn):
    """Fetch all user_tenant records from database"""
    try:
        cursor = conn.cursor()
        query = """
                SELECT user_id, tenant_id, user_role, user_email
                FROM nexent.user_tenant_t
                WHERE delete_flag = 'N'
                ORDER BY user_id \
                """
        cursor.execute(query)
        records = cursor.fetchall()
        cursor.close()

        # Convert to list of dicts
        result = []
        for row in records:
            result.append({
                'user_id': row[0],
                'tenant_id': row[1],
                'user_role': row[2],
                'user_email': row[3]
            })

        logger.info(f"Fetched {len(result)} user_tenant records from database")
        return result
    except Exception as e:
        logger.error(f"Failed to fetch user_tenant records: {e}")
        return []


def get_user_email_from_supabase(user_id, supabase_url, service_role_key):
    """
    Get user email from Supabase by user ID using REST API.

    Args:
        user_id: The user's UUID
        supabase_url: Supabase API URL
        service_role_key: Service role key for admin access

    Returns:
        User's email address or None if not found

    Note: SPEED system user (user_id="user_id") is virtual and doesn't exist in Supabase.
    """
    # Skip Supabase lookup for virtual SPEED system user
    if user_id == DEFAULT_USER_ID:
        logger.debug(f"User {user_id} is virtual SPEED user, skipping Supabase lookup")
        return None

    if not supabase_url or not service_role_key:
        logger.warning("Supabase URL or service role key not configured")
        return None

    # Clean up URL (remove trailing slash)
    supabase_url = supabase_url.rstrip('/')

    try:
        headers = {
            'Authorization': f'Bearer {service_role_key}',
            'apikey': service_role_key,
            'Content-Type': 'application/json'
        }

        # Get user by ID via REST API
        response = requests.get(
            f'{supabase_url}/auth/v1/admin/users/{user_id}',
            headers=headers,
            timeout=10
        )

        if response.status_code == 200:
            user_data = response.json()
            email = user_data.get('email')
            if email:
                logger.debug(f"Fetched email for user {user_id}: {email}")
                return email
            else:
                logger.warning(f"User {user_id} has no email in Supabase")
                return None
        elif response.status_code == 404:
            logger.warning(f"User {user_id} not found in Supabase")
            return None
        elif response.status_code == 401:
            logger.error("Unauthorized: Check your SERVICE_ROLE_KEY")
            return None
        else:
            logger.warning(f"Failed to fetch user {user_id}: HTTP {response.status_code} - {response.text}")
            return None

    except requests.exceptions.ConnectionError as e:
        logger.warning(f"Cannot connect to Supabase for user {user_id}: {e}")
        return None
    except requests.exceptions.Timeout as e:
        logger.warning(f"Request timeout for user {user_id}: {e}")
        return None
    except Exception as e:
        logger.warning(f"Error fetching user {user_id} from Supabase: {e}")
        return None


def determine_user_role(user_id, tenant_id, user_email):
    """
    Determine user_role based on rules:
    1. Special case: user_id == "user_id" AND tenant_id == "tenant_id" → SPEED (default system user)
    2. If user_id == tenant_id → ADMIN
    3. If user_email == LEGACY_ADMIN_EMAIL → ADMIN
    4. Otherwise → USER
    """
    # Rule 0: Default system user (user_id="user_id", tenant_id="tenant_id") → SPEED
    if user_id == DEFAULT_USER_ID and tenant_id == DEFAULT_TENANT_ID:
        return "SPEED"

    # Rule 1: user_id == tenant_id → ADMIN
    if user_id == tenant_id:
        return "ADMIN"

    # Rule 2: Special admin email → ADMIN
    if user_email and user_email.lower() == LEGACY_ADMIN_EMAIL.lower():
        return "ADMIN"

    # Default: USER
    return "USER"


def update_user_record(conn, user_id, user_email, user_role):
    """Update a single user record in database"""
    try:
        cursor = conn.cursor()
        query = """
                UPDATE nexent.user_tenant_t
                SET user_email  = %s,
                    user_role   = %s,
                    updated_by  = 'system',
                    update_time = NOW()
                WHERE user_id = %s \
                  AND delete_flag = 'N' \
                """
        cursor.execute(query, (user_email, user_role, user_id))
        affected = cursor.rowcount
        cursor.close()
        conn.commit()
        return affected > 0
    except Exception as e:
        logger.error(f"Failed to update user {user_id}: {e}")
        conn.rollback()
        return False


def process_user_records(conn, supabase_params, records, dry_run=False):
    """
    Process all user records:
    1. Fetch email from Supabase (if not already set or overwrite is True)
    2. Determine user_role based on rules
    3. Update database
    """
    supabase_url = supabase_params['url']
    service_role_key = supabase_params['key']

    results = {
        'total': len(records),
        'updated': 0,
        'skipped': 0,
        'failed': 0,
        'details': []
    }

    for record in records:
        user_id = record['user_id']
        tenant_id = record['tenant_id']
        old_email = record.get('user_email')
        old_role = record.get('user_role')

        # Get email from Supabase using REST API
        user_email = get_user_email_from_supabase(user_id, supabase_url, service_role_key)

        if not user_email:
            # Keep existing email if no new email from Supabase
            user_email = old_email
            if not old_email:
                logger.warning(f"Could not fetch email from Supabase for user {user_id}, and no existing email")

        # Determine user_role
        user_role = determine_user_role(user_id, tenant_id, user_email)

        # Check if update is needed
        email_changed = user_email != old_email
        role_changed = user_role != old_role

        if not email_changed and not role_changed:
            results['skipped'] += 1
            results['details'].append({
                'user_id': user_id,
                'status': 'skipped',
                'reason': 'No changes needed'
            })
            continue

        if dry_run:
            logger.info(f"[DRY-RUN] Would update user {user_id}:")
            logger.info(f"  Email: {old_email} -> {user_email}")
            logger.info(f"  Role: {old_role} -> {user_role}")
            results['updated'] += 1
            results['details'].append({
                'user_id': user_id,
                'status': 'dry-run',
                'old_email': old_email,
                'new_email': user_email,
                'old_role': old_role,
                'new_role': user_role
            })
        else:
            if update_user_record(conn, user_id, user_email, user_role):
                logger.info(f"Updated user {user_id}: email={user_email}, role={user_role}")
                results['updated'] += 1
                results['details'].append({
                    'user_id': user_id,
                    'status': 'success',
                    'old_email': old_email,
                    'new_email': user_email,
                    'old_role': old_role,
                    'new_role': user_role
                })
            else:
                results['failed'] += 1
                results['details'].append({
                    'user_id': user_id,
                    'status': 'failed',
                    'reason': 'Update failed'
                })

    return results


def print_results(results):
    """Print processing results"""
    logger.info("=" * 60)
    logger.info("Processing Results:")
    logger.info(f"  Total records: {results['total']}")
    logger.info(f"  Updated: {results['updated']}")
    logger.info(f"  Skipped: {results['skipped']}")
    logger.info(f"  Failed: {results['failed']}")
    logger.info("=" * 60)

    # Print details for updated records
    if results['details']:
        logger.info("\nUpdated/Skipped Records:")
        for detail in results['details']:
            if detail['status'] in ['success', 'dry-run']:
                logger.info(f"  User {detail['user_id']}:")
                if 'new_email' in detail:
                    logger.info(f"    Email: {detail['old_email']} -> {detail['new_email']}")
                if 'new_role' in detail:
                    logger.info(f"    Role: {detail['old_role']} -> {detail['new_role']}")


def test_supabase_connection(supabase_params):
    """Test Supabase connection by listing users"""
    supabase_url = supabase_params['url'].rstrip('/')
    service_role_key = supabase_params['key']

    try:
        headers = {
            'Authorization': f'Bearer {service_role_key}',
            'apikey': service_role_key,
            'Content-Type': 'application/json'
        }

        # Test by listing users (limit 1)
        response = requests.get(
            f'{supabase_url}/auth/v1/admin/users?page=1&per_page=1',
            headers=headers,
            timeout=10
        )

        if response.status_code == 200:
            logger.info("Supabase connection test: SUCCESS")
            return True
        elif response.status_code == 401:
            logger.error("Supabase connection test: FAILED (401 Unauthorized)")
            logger.error("Please check your SERVICE_ROLE_KEY")
            return False
        else:
            logger.warning(f"Supabase connection test: HTTP {response.status_code}")
            return False

    except requests.exceptions.ConnectionError as e:
        logger.error(f"Cannot connect to Supabase: {e}")
        return False
    except Exception as e:
        logger.error(f"Supabase connection test failed: {e}")
        return False


def main():
    """Main function"""
    parser = argparse.ArgumentParser(
        description='Update user data for v2 upgrade'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be updated without making changes'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose debug output'
    )
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    logger.info("=" * 60)
    logger.info("User Data Update Script (v2 upgrade)")
    logger.info("=" * 60)

    if args.dry_run:
        logger.info("Mode: DRY-RUN (no changes will be made)")

    # Step 0: Check Docker containers
    logger.info("\n[Step 0/6] Checking Docker containers...")
    docker_status = check_docker_containers()
    if docker_status is False:
        logger.error("Required Docker containers are not running")
        logger.info("Ensure nexent-postgresql container is running")
        sys.exit(1)

    # Step 1: Validate environment variables
    logger.info("\n[Step 1/6] Loading environment variables...")
    if not load_environment_from_container():
        logger.error("Failed to load environment variables")
        sys.exit(1)

    # Step 2: Get Supabase parameters and test connection
    logger.info("\n[Step 2/6] Testing Supabase connection...")
    supabase_params = get_supabase_params()
    if not supabase_params['url'] or not supabase_params['key']:
        logger.error("SUPABASE_URL and SERVICE_ROLE_KEY must be set in environment")
        sys.exit(1)

    logger.info(f"  Supabase URL: {supabase_params['url']}")
    logger.info(f"  Service Role Key: {supabase_params['key'][:20]}...{supabase_params['key'][-10:]}")

    if not test_supabase_connection(supabase_params):
        logger.error("Failed to connect to Supabase")
        sys.exit(1)

    # Step 3: Connect to database
    logger.info("\n[Step 3/6] Connecting to PostgreSQL database...")
    conn_params = get_postgres_connection_params()
    conn = get_db_connection(conn_params)
    if not conn:
        logger.error("Failed to connect to database")
        # Try psql as fallback
        test_connection_with_psql(conn_params)
        sys.exit(1)

    try:
        # Step 4: Fetch all user_tenant records
        logger.info("\n[Step 4/6] Fetching user_tenant records...")
        records = fetch_all_user_tenant_records(conn)
        if not records:
            logger.warning("No user_tenant records found")
            return

        # Step 5: Process records
        logger.info("\n[Step 5/6] Processing records...")
        results = process_user_records(conn, supabase_params, records, dry_run=args.dry_run)
        print_results(results)

        # Step 6: Summary
        logger.info("\n[Step 6/6] Upgrade completed")

        if args.dry_run:
            logger.info("\nTo apply these changes, run without --dry-run flag")

    finally:
        # Close database connection
        if conn:
            conn.close()
            logger.info("\nDatabase connection closed")


if __name__ == "__main__":
    main()
