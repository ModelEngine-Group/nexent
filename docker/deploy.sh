#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

ERROR_OCCURRED=0

set -a
source .env

# Parse arg
MODE_CHOICE=""
IS_MAINLAND=""
ENABLE_TERMINAL=""
VERSION_CHOICE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode)
      MODE_CHOICE="$2"
      shift 2
      ;;
    --is-mainland)
      IS_MAINLAND="$2"
      shift 2
      ;;
    --enable-terminal)
      ENABLE_TERMINAL="$2"
      shift 2
      ;;
    --version)
      VERSION_CHOICE="$2"
      shift 2
      ;;
    *)
      shift
      ;;
  esac
done

# 尝试获取 Docker Compose 版本信息（兼容 V1 和 V2）
# try get the version of docker compose
get_compose_version() {
    # 优先尝试 V2 命令
    if command -v docker &> /dev/null; then
        version_output=$(docker compose version 2>/dev/null)
        if [[ $version_output =~ (v[0-9]+\.[0-9]+\.[0-9]+) ]]; then
            echo "v2 ${BASH_REMATCH[1]}"
            return 0
        fi
    fi

    # 如果 V2 失败，尝试 V1 命令
    if command -v docker-compose &> /dev/null; then
        version_output=$(docker-compose --version 2>/dev/null)
        if [[ $version_output =~ ([0-9]+\.[0-9]+\.[0-9]+) ]]; then
            echo "v1 ${BASH_REMATCH[1]}"
            return 0
        fi
    fi

    echo "unknown"
    return 1
}

# Function to install Supabase services based on DEPLOYMENT_VERSION
install_supabase_services() {
    # Only install docker-compose-supabase if DEPLOYMENT_VERSION is "full"
    if [ "$DEPLOYMENT_VERSION" = "full" ]; then
        echo "🎯 Full version detected - installing Supabase services..."
        
        # Check if the supabase compose file exists
        if [ ! -f "docker-compose-supabase${COMPOSE_FILE_SUFFIX}" ]; then
            echo "❌ ERROR Supabase compose file not found: docker-compose-supabase${COMPOSE_FILE_SUFFIX}"
            ERROR_OCCURRED=1
            return 1
        fi
        
        # Start Supabase services
        if ! docker-compose -p nexent -f "docker-compose-supabase${COMPOSE_FILE_SUFFIX}" up -d; then
            echo "❌ ERROR Failed to start supabase services"
            ERROR_OCCURRED=1
            return 1
        fi
        
        echo "✅ Supabase services started successfully"
    else
        echo "⚡ Speed version detected - skipping Supabase services"
    fi
}

# 获取版本信息
# get docker compose version
version_info=$(get_compose_version)
if [[ $version_info == "unknown" ]]; then
    echo "Error: Docker Compose not found or version detection failed"
    exit 1
fi

# 解析版本类型和版本号
# extract version
version_type=$(echo "$version_info" | awk '{print $1}')
version_number=$(echo "$version_info" | awk '{print $2}')


# 根据版本类型执行不同操作
# define docker compose command
docker_compose_command=""
case $version_type in
    "v1")
        echo "Detected Docker Compose V1, version: $version_number"
        # 这里添加 V1 版本特定的操作. v1.28.0是明确支持 ${VAR:-default} 这类带默认值的插值语法的最低版本
        # The version ​​v1.28.0​​ is the minimum requirement in Docker Compose v1 that explicitly supports interpolation syntax with default values like ${VAR:-default}
        if [[ $version_number < "1.28.0" ]]; then
            echo "Warning: V1 version is too old, consider upgrading to V2"
            exit 1
        fi
        docker_compose_command="docker-compose"
        ;;
    "v2")
        echo "Detected Docker Compose V2, version: $version_number"
        docker_compose_command="docker compose"
        ;;
    *)
        echo "Error: Unknown docker compose version type."
        exit 1
        ;;
esac

# Add deployment mode selection function
select_deployment_mode() {
    echo "🎛️  Please select deployment mode:"
    echo "1) 🛠️  Development mode - Expose all service ports for debugging"
    echo "2) 🏗️  Infrastructure mode - Only start infrastructure services"
    echo "3) 🚀 Production mode - Only expose port 3000 for security"
    echo "4) 🧪 Beta mode - Use develop branch images (from .env.beta)"
    if [ -n "$MODE_CHOICE" ]; then
      mode_choice="$MODE_CHOICE"
      echo "👉 Using mode_choice from argument: $mode_choice"
    else
      read -p "👉 Enter your choice [1/2/3/4] (default: 1): " mode_choice
    fi

    local root_dir="# Root dir"
    case $mode_choice in
        2)
            export DEPLOYMENT_MODE="infrastructure"
            export COMPOSE_FILE_SUFFIX=".yml"
            echo "✅ Selected infrastructure mode 🏗️"
            ;;
        3)
            export DEPLOYMENT_MODE="production"
            export COMPOSE_FILE_SUFFIX=".prod.yml"
            # Set environment variables to disable dashboards in production
            export DISABLE_RAY_DASHBOARD="true"
            export DISABLE_CELERY_FLOWER="true"
            echo "✅ Selected production mode deployment"
            if ! grep -q "$root_dir" .env; then
              sed -i -e '$a\' .env
              echo "# Root dir" >> .env
              echo "ROOT_DIR=\"$HOME/nexent-production-data\"" >> .env
            fi
            ;;
        4)
            export DEPLOYMENT_MODE="beta"
            export COMPOSE_FILE_SUFFIX=".yml"
            echo "✅ Selected beta mode 🧪"
            ;;
        *)
            export DEPLOYMENT_MODE="development"
            export COMPOSE_FILE_SUFFIX=".yml"
            echo "✅ Selected development mode deployment"
            if ! grep -q "$root_dir" .env; then
              sed -i -e '$a\' .env
              echo "# Root dir" >> .env
              echo "ROOT_DIR=\"$HOME/nexent-development-data\"" >> .env
            fi
            ;;
    esac
    echo ""
    echo "--------------------------------"
    echo ""
}

clean() {
  # export MINIO_ACCESS_KEY=
  # export MINIO_SECRET_KEY=
  export DEPLOYMENT_MODE=
  export COMPOSE_FILE_SUFFIX=
  export DEPLOYMENT_VERSION=
}

# Function to create a directory and set permissions
create_dir_with_permission() {
    local dir_path="$1"
    local permission="$2"

    # Check if parameters are provided
    if [ -z "$dir_path" ] || [ -z "$permission" ]; then
        echo "❌ ERROR Directory path and permission parameters are required." >&2
        ERROR_OCCURRED=1
        return 1
    fi

    # Create the directory if it doesn't exist
    if [ ! -d "$dir_path" ]; then
        mkdir -p "$dir_path"
        if [ $? -ne 0 ]; then
            echo "❌ ERROR Failed to create directory $dir_path." >&2
            ERROR_OCCURRED=1
            return 1
        fi
    fi

    # Set directory permissions
    chmod -R "$permission" "$dir_path"
    if [ $? -ne 0 ]; then
        echo "❌ ERROR Failed to set permissions $permission for directory $dir_path." >&2
        ERROR_OCCURRED=1
        return 1
    fi

    echo "📁 Directory $dir_path has been created and permissions set to $permission."
}

add_permission() {
  # Initialize the sql script permission
  chmod 644 "init.sql"

  create_dir_with_permission "$ROOT_DIR/elasticsearch" 777
  create_dir_with_permission "$ROOT_DIR/postgresql" 777
  create_dir_with_permission "$ROOT_DIR/minio" 777

  cp -rn volumes $ROOT_DIR

  # Create nexent user workspace directory
  NEXENT_USER_DIR="$HOME/nexent"
  create_dir_with_permission "$NEXENT_USER_DIR" 775
  echo "📁 Created Nexent user workspace at: $NEXENT_USER_DIR"

  # Export for docker-compose
  export NEXENT_USER_DIR

  echo ""
  echo "--------------------------------"
  echo ""
}

# Function to install services for non-infrastructure modes
install() {
  # Build base infrastructure command
  INFRA_SERVICES="nexent-elasticsearch nexent-postgresql nexent-minio redis"

  # Add openssh-server if Terminal tool is enabled
  if [ "$ENABLE_TERMINAL_TOOL" = "true" ]; then
    INFRA_SERVICES="$INFRA_SERVICES nexent-openssh-server"
    echo "🔧 Terminal tool enabled - openssh-server will be included"
  fi

  # Set profiles for docker-compose if any are defined
  if [ -n "$COMPOSE_PROFILES" ]; then
    export COMPOSE_PROFILES
    echo "📋 Using profiles: $COMPOSE_PROFILES"
  fi

  # Start infrastructure services
  if ! docker-compose -p nexent -f "docker-compose${COMPOSE_FILE_SUFFIX}" up -d $INFRA_SERVICES; then
    echo "❌ ERROR Failed to start infrastructure services"
    ERROR_OCCURRED=1
    return 1
  fi

  # Install Supabase services based on deployment version
  install_supabase_services || {
    echo "❌ ERROR Supabase services installation failed"
    ERROR_OCCURRED=1
    return 1
  }

  echo ""
  echo "--------------------------------"
  echo ""

  # Always generate a new ELASTICSEARCH_API_KEY for each deployment.
  echo "🔑 Generating ELASTICSEARCH_API_KEY..."
  # Wait for elasticsearch health check
  while ! ${docker_compose_command} -p nexent -f "docker-compose${COMPOSE_FILE_SUFFIX}" ps nexent-elasticsearch | grep -q "healthy"; do
    echo "⏳ Waiting for Elasticsearch to become healthy..."
    sleep 10
  done

  # Generate API key
  API_KEY_JSON=$(${docker_compose_command} -p nexent -f "docker-compose${COMPOSE_FILE_SUFFIX}" exec -T nexent-elasticsearch curl -s -u "elastic:$ELASTIC_PASSWORD" "http://localhost:9200/_security/api_key" -H "Content-Type: application/json" -d '{"name":"my_api_key","role_descriptors":{"my_role":{"cluster":["all"],"index":[{"names":["*"],"privileges":["all"]}]}}}')

  # Extract API key and add to .env
  ELASTICSEARCH_API_KEY=$(echo "$API_KEY_JSON" | grep -o '"encoded":"[^"]*"' | awk -F'"' '{print $4}')
  if [ -n "$ELASTICSEARCH_API_KEY" ]; then
    if grep -q "^ELASTICSEARCH_API_KEY=" .env; then
      # Use ~ as a separator in sed to avoid conflicts with special characters in the API key.
      sed -i.bak "s~^ELASTICSEARCH_API_KEY=.*~ELASTICSEARCH_API_KEY=$ELASTICSEARCH_API_KEY~" .env
      rm .env.bak
    else
      echo "" >> .env
      echo "ELASTICSEARCH_API_KEY=$ELASTICSEARCH_API_KEY" >> .env
    fi
  fi

  wait_for_elasticsearch_healthy || {
    echo "❌ ERROR Elasticsearch health check failed"
    ERROR_OCCURRED=1
    return 1
  }

  echo ""
  echo "--------------------------------"
  echo ""

  # Start core services
  if [ "$DEPLOYMENT_MODE" != "infrastructure" ]; then
    echo "👀 Starting core services..."
    if ! docker-compose -p nexent -f "docker-compose${COMPOSE_FILE_SUFFIX}" up -d nexent nexent-web nexent-data-process; then
      echo "❌ ERROR Failed to start core services"
      ERROR_OCCURRED=1
      return 1
    fi
  fi
  echo "Deploying services in ${DEPLOYMENT_MODE} mode..."
}


# 生成JWT的函数
generate_jwt() {
  local role=$1
  local secret=$JWT_SECRET
  local now=$(date +%s)
  local exp=$((now + 157680000))

  local header='{"alg":"HS256","typ":"JWT"}'
  local header_base64=$(echo -n "$header" | base64 | tr -d '\n=' | tr '/+' '_-')

  local payload="{\"role\":\"$role\",\"iss\":\"supabase\",\"iat\":$now,\"exp\":$exp}"
  local payload_base64=$(echo -n "$payload" | base64 | tr -d '\n=' | tr '/+' '_-')

  local signature=$(echo -n "$header_base64.$payload_base64" | openssl dgst -sha256 -hmac "$secret" -binary | base64 | tr -d '\n=' | tr '/+' '_-')

  echo "$header_base64.$payload_base64.$signature"
}

# Function to update or add a key-value pair to .env
update_env_var() {
  local key="$1"
  local value="$2"
  local env_file=".env"

  # Ensure the .env file exists
  touch "$env_file"

  if grep -q "^${key}=" "$env_file"; then
    # Key exists, so update it. Escape \ and & for sed's replacement string.
    # Use ~ as the separator to avoid issues with / in the value.
    local escaped_value=$(echo "$value" | sed -e 's/\\/\\\\/g' -e 's/&/\\&/g')
    sed -i.bak "s~^${key}=.*~${key}=\"${escaped_value}\"~" "$env_file"
  else
    # Key doesn't exist, so add it
    echo "${key}=\"${value}\"" >> "$env_file"
    echo ""
    echo "--------------------------------"
    echo ""
  fi

}

# Add deployment version selection function
select_deployment_version() {
    echo "🚀 Please select deployment version:"
    echo "1) ⚡ Speed version - Lightweight deployment with essential features"
    echo "2) 🎯 Full version - Full-featured deployment with all capabilities"
    if [ -n "$VERSION_CHOICE" ]; then
      version_choice="$VERSION_CHOICE"
      echo "👉 Using version_choice from argument: $version_choice"
    else
      read -p "👉 Enter your choice [1/2] (default: 1): " version_choice
    fi

    case $version_choice in
        2)
            export DEPLOYMENT_VERSION="full"
            echo "✅ Selected complete version 🎯"
            ;;
        *)
            export DEPLOYMENT_VERSION="speed"
            echo "✅ Selected speed version ⚡"
            ;;
    esac
    
    # Save the version choice to .env file
    update_env_var "DEPLOYMENT_VERSION" "$DEPLOYMENT_VERSION"
    
    echo ""
    echo "--------------------------------"
    echo ""
}

choose_image_env() {
  if [ -n "$IS_MAINLAND" ]; then
    is_mainland="$IS_MAINLAND"
    echo "🌏 Using is_mainland from argument: $is_mainland"
  else
    read -p "🌏 Is your server network located in mainland China? [Y/N] (default N): " is_mainland
  fi
  if [[ "$is_mainland" =~ ^[Yy]$ ]]; then
    echo "🌐 Detected mainland China network, using .env.mainland for image sources."
    source .env.mainland
  else
    echo "🌐 Using general image sources from .env.general."
    source .env.general
  fi

  echo ""
  echo "--------------------------------"
  echo ""
}

choose_beta_env() {
  echo "🌐 Beta mode selected, using .env.beta for image sources."
  source .env.beta
  echo ""
  echo "--------------------------------"
  echo ""
}

# Function to pull required images
pull_required_images() {
  echo "🐳 Pulling openssh-server image for Terminal tool..."
  if ! docker pull "$OPENSSH_SERVER_IMAGE"; then
    echo "❌ ERROR Failed to pull openssh-server image: $OPENSSH_SERVER_IMAGE"
    ERROR_OCCURRED=1
    return 1
  fi
  echo "✅ Successfully pulled openssh-server image"
  echo ""
  echo "--------------------------------"
  echo ""
}



# Function to setup package installation script
setup_package_install_script() {
  echo "📝 Setting up package installation script..."
  mkdir -p "openssh-server/config/custom-cont-init.d"

  # Copy the fixed installation script
  if [ -f "openssh-install-script.sh" ]; then
      cp "openssh-install-script.sh" "openssh-server/config/custom-cont-init.d/openssh-start-script"
      chmod +x "openssh-server/config/custom-cont-init.d/openssh-start-script"
      echo "✅ Package installation script created/updated"
  else
      echo "❌ ERROR openssh-install-script.sh not found"
      ERROR_OCCURRED=1
      return 1
  fi
}

# Function to wait for Elasticsearch to become healthy
wait_for_elasticsearch_healthy() {
    local retries=0
    local max_retries=${1:-60}  # Default 10 minutes, can be overridden
    while ! docker-compose -p nexent -f "docker-compose${COMPOSE_FILE_SUFFIX}" ps nexent-elasticsearch | grep -q "healthy" && [ $retries -lt $max_retries ]; do
        echo "⏳ Waiting for Elasticsearch to become healthy... (attempt $((retries + 1))/$max_retries)"
        sleep 10
        retries=$((retries + 1))
    done

    if [ $retries -eq $max_retries ]; then
        echo "⚠️  Warning: Elasticsearch did not become healthy within expected time"
        echo "   You may need to check the container logs and try again"
        return 1
    else
        echo "✅ Elasticsearch is now healthy!"
        return 0
    fi
}

# Function to generate complete environment file for infrastructure mode using generate_env.sh
generate_env_for_infrastructure() {
    # Wait for Elasticsearch to be healthy first
    wait_for_elasticsearch_healthy || {
        echo "⚠️  Elasticsearch is not healthy, but continuing with environment generation..."
    }
    echo ""
    echo "--------------------------------"
    echo ""
    echo "🚀 Running generate_env.sh to create complete environment..."

    # Check if generate_env.sh exists
    if [ ! -f "generate_env.sh" ]; then
        echo "❌ ERROR generate_env.sh not found in docker directory"
        return 1
    fi

    # Make sure the script is executable and run it
    chmod +x generate_env.sh
    
    # Export DEPLOYMENT_VERSION to ensure generate_env.sh can access it
    export DEPLOYMENT_VERSION
    
    if ./generate_env.sh; then
        echo "--------------------------------"
        echo ""
        echo "✅ Environment file generated successfully for infrastructure mode!"

        # Source the generated .env file to make variables available
        if [ -f "../.env" ]; then
            echo "📁 Sourcing generated .env file..."
            set -a
            source ../.env
            set +a
            echo "✅ Environment variables loaded from ../.env"
        else
            echo "⚠️  Warning: ../.env file not found after generation"
            return 1
        fi
    else
        echo "❌ ERROR Failed to generate environment file"
        return 1
    fi

    echo ""
    echo "--------------------------------"
    echo ""
}

# Function to ask if user wants to enable Terminal tool
select_terminal_tool() {
    echo "🔧 Terminal Tool Configuration:"
    echo "Terminal tool allows AI agents to execute shell commands via SSH."
    echo "This creates an openssh-server container for secure command execution."
    if [ -n "$ENABLE_TERMINAL" ]; then
        enable_terminal="$ENABLE_TERMINAL"
    else
        read -p "👉 Do you want to enable Terminal tool? [Y/N] (default: N): " enable_terminal
    fi

    if [[ "$enable_terminal" =~ ^[Yy]$ ]]; then
        export ENABLE_TERMINAL_TOOL="true"
        export COMPOSE_PROFILES="${COMPOSE_PROFILES:+$COMPOSE_PROFILES,}terminal"
        echo "✅ Terminal tool enabled 🔧"
        echo "📝 An openssh-server container will be deployed for secure command execution."
    else
        export ENABLE_TERMINAL_TOOL="false"
        echo "❌ Terminal tool disabled"
    fi
    echo ""
    echo "--------------------------------"
    echo ""
}

# Function to generate SSH key pair for Terminal tool
generate_ssh_keys() {
    if [ "$ENABLE_TERMINAL_TOOL" = "true" ]; then
        # Create ssh-keys directory
        create_dir_with_permission "openssh-server/ssh-keys" 700
        create_dir_with_permission "openssh-server/config" 755

        # Check if SSH keys already exist
        if [ -f "openssh-server/ssh-keys/openssh_server_key" ] && [ -f "openssh-server/ssh-keys/openssh_server_key.pub" ]; then
            echo "🔑 SSH key pair already exists, skipping generation..."
            echo "🔑 Private key: openssh-server/ssh-keys/openssh_server_key"
            echo "🗝️  Public key: openssh-server/ssh-keys/openssh_server_key.pub"

            # Ensure authorized_keys is set up correctly with ONLY our public key
            cp "openssh-server/ssh-keys/openssh_server_key.pub" "openssh-server/config/authorized_keys"
            chmod 644 "openssh-server/config/authorized_keys"

            # Setup package installation script
            setup_package_install_script

            # Set SSH key path in environment
            SSH_PRIVATE_KEY_PATH="$(pwd)/openssh-server/ssh-keys/openssh_server_key"
            export SSH_PRIVATE_KEY_PATH

            # Add to .env file
            if grep -q "^SSH_PRIVATE_KEY_PATH=" .env; then
                sed -i.bak "s~^SSH_PRIVATE_KEY_PATH=.*~SSH_PRIVATE_KEY_PATH=$SSH_PRIVATE_KEY_PATH~" .env
                rm .env.bak
            else
                echo "SSH_PRIVATE_KEY_PATH=$SSH_PRIVATE_KEY_PATH" >> .env
            fi

            echo ""
            echo "--------------------------------"
            echo ""
            return 0
        fi

        echo "🔑 Generating SSH key pair for Terminal tool..."

        # Generate SSH key pair using Docker (cross-platform compatible)
        echo "🔐 Using Docker to generate SSH key pair..."

        # Create temporary file to capture output
        TEMP_OUTPUT="/tmp/ssh_keygen_output_$$.txt"

        # Generate ed25519 key pair using the openssh-server container
        if docker run --rm -i --entrypoint //keygen.sh "$OPENSSH_SERVER_IMAGE" <<< "1" > "$TEMP_OUTPUT" 2>&1; then
            echo "🔍 SSH key generation completed, extracting keys..."

            # Extract private key (everything between -----BEGIN and -----END)
            PRIVATE_KEY=$(sed -n '/-----BEGIN OPENSSH PRIVATE KEY-----/,/-----END OPENSSH PRIVATE KEY-----/p' "$TEMP_OUTPUT")

            # Extract public key (line that starts with ssh-)
            PUBLIC_KEY=$(grep "^ssh-" "$TEMP_OUTPUT" | head -1)

            # Remove leading/trailing whitespace
            PRIVATE_KEY=$(echo "$PRIVATE_KEY" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
            PUBLIC_KEY=$(echo "$PUBLIC_KEY" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')

            # Validate extracted keys
            if [ -z "$PRIVATE_KEY" ]; then
                echo "❌ Failed to extract private key"
                ERROR_OCCURRED=1
                return 1
            fi

            if [ -z "$PUBLIC_KEY" ]; then
                echo "❌ Failed to extract public key"
                ERROR_OCCURRED=1
                return 1
            fi

            echo "✅ SSH keys extracted successfully"

            if [ -n "$PRIVATE_KEY" ] && [ -n "$PUBLIC_KEY" ]; then
                # Save private key
                echo "$PRIVATE_KEY" > "openssh-server/ssh-keys/openssh_server_key"
                chmod 600 "openssh-server/ssh-keys/openssh_server_key"

                # Save public key
                echo "$PUBLIC_KEY" > "openssh-server/ssh-keys/openssh_server_key.pub"
                chmod 644 "openssh-server/ssh-keys/openssh_server_key.pub"

                # Copy public key to authorized_keys with correct permissions (ensure ONLY our key)
                cp "openssh-server/ssh-keys/openssh_server_key.pub" "openssh-server/config/authorized_keys"
                chmod 644 "openssh-server/config/authorized_keys"

                # Setup package installation script
                setup_package_install_script

                # Set SSH key path in environment
                SSH_PRIVATE_KEY_PATH="$(pwd)/openssh-server/ssh-keys/openssh_server_key"
                export SSH_PRIVATE_KEY_PATH

                # Add to .env file
                if grep -q "^SSH_PRIVATE_KEY_PATH=" .env; then
                    sed -i.bak "s~^SSH_PRIVATE_KEY_PATH=.*~SSH_PRIVATE_KEY_PATH=$SSH_PRIVATE_KEY_PATH~" .env
                    rm .env.bak
                else
                    echo "SSH_PRIVATE_KEY_PATH=$SSH_PRIVATE_KEY_PATH" >> .env
                fi

                # Fix SSH host key permissions (must be 600)
                find "openssh-server/config" -name "*_key" -type f -exec chmod 600 {} \; 2>/dev/null || true

                echo "✅ SSH key pair generated successfully!"
                echo "🔑 Private key: openssh-server/ssh-keys/openssh_server_key"
                echo "🗝️  Public key: openssh-server/ssh-keys/openssh_server_key.pub"
                echo "⚙️  SSH config: openssh-server/config/sshd_config (60min session timeout)"
            else
                echo "❌ ERROR Failed to extract SSH keys from Docker output"
                echo "📋 Full output saved to: $TEMP_OUTPUT for debugging"
                ERROR_OCCURRED=1
                return 1
            fi
        else
            echo "❌ ERROR Docker key generation command failed"
            if [ -f "$TEMP_OUTPUT" ]; then
                echo "📋 Error output:"
                cat "$TEMP_OUTPUT"
            fi
            ERROR_OCCURRED=1
            return 1
        fi

        # Clean up temp file (only if successful)
        if [ "$ERROR_OCCURRED" -eq 0 ]; then
            rm -f "$TEMP_OUTPUT"
        fi

        echo ""
        echo "--------------------------------"
        echo ""
    fi
}

generate_minio_ak_sk() {
  echo "🔑 Generating MinIO access keys..."

  if [ "$(uname -s | tr '[:upper:]' '[:lower:]')" = "mingw" ] || [ "$(uname -s | tr '[:upper:]' '[:lower:]')" = "msys" ]; then
    # Windows
    ACCESS_KEY=$(powershell -Command "[System.Convert]::ToBase64String([System.Guid]::NewGuid().ToByteArray()) -replace '[^a-zA-Z0-9]', '' -replace '=.+$', '' | Select-Object -First 12")
    SECRET_KEY=$(powershell -Command '$rng = [System.Security.Cryptography.RandomNumberGenerator]::Create(); $bytes = New-Object byte[] 32; $rng.GetBytes($bytes); [System.Convert]::ToBase64String($bytes)')
  else
    # Linux/Mac
    # Generate a random AK (12-character alphanumeric) and clean it
    ACCESS_KEY=$(openssl rand -hex 12 | tr -d '\r\n' | sed 's/[^a-zA-Z0-9]//g')

    # Generate a random SK (32-character high-strength random string) and clean it
    SECRET_KEY=$(openssl rand -base64 32 | tr -d '\r\n' | sed 's/[^a-zA-Z0-9+/=]//g')
  fi

  if [ -z "$ACCESS_KEY" ] || [ -z "$SECRET_KEY" ]; then
    echo "❌ ERROR Failed to generate MinIO access keys"
    ERROR_OCCURRED=1
    return 1
  fi

  export MINIO_ACCESS_KEY=$ACCESS_KEY
  export MINIO_SECRET_KEY=$SECRET_KEY

  if grep -q "^MINIO_ACCESS_KEY=" .env; then
    sed -i.bak "s~^MINIO_ACCESS_KEY=.*~MINIO_ACCESS_KEY=$ACCESS_KEY~" .env
    rm .env.bak
  else
    echo "MINIO_ACCESS_KEY=$ACCESS_KEY" >> .env
  fi

  if grep -q "^MINIO_SECRET_KEY=" .env; then
    sed -i.bak "s~^MINIO_SECRET_KEY=.*~MINIO_SECRET_KEY=$SECRET_KEY~" .env
    rm .env.bak
  else
    echo "MINIO_SECRET_KEY=$SECRET_KEY" >> .env
  fi

  echo "✅ MinIO access keys generated successfully"
}

# Main execution flow
echo  "🚀  Nexent Deployment Script"
echo ""
echo "--------------------------------"
echo ""

# Main deployment function
main_deploy() {
  # Start deployment

  # Select deployment version and mode
  select_deployment_version || { echo "❌ Deployment version selection failed"; exit 1; }
  select_deployment_mode || { echo "❌ Deployment mode selection failed"; exit 1; }
  select_terminal_tool || { echo "❌ Terminal tool configuration failed"; exit 1; }
    
  # Choose image environment before generating keys that need Docker images
  if [ "$DEPLOYMENT_MODE" = "beta" ]; then
    choose_beta_env || { echo "❌ Beta environment setup failed"; exit 1; }
  else
    choose_image_env || { echo "❌ Image environment setup failed"; exit 1; }
  fi

  # Add permission
  add_permission || { echo "❌ Permission setup failed"; exit 1; }

  if [ "$ENABLE_TERMINAL_TOOL" = "true" ]; then
    # Pull required images before using them
    pull_required_images || { echo "❌ Required image pull failed"; exit 1; }
    
    # Generate SSH keys for terminal tool (only needed if terminal tool is enabled)
    generate_ssh_keys || { echo "❌ SSH key generation failed"; exit 1; }
  fi

  # Special handling for infrastructure mode
  if [ "$DEPLOYMENT_MODE" = "infrastructure" ]; then
    echo "🏗️  Infrastructure mode detected - preparing infrastructure services..."
    
    # Start infrastructure services (basic services only)
    echo "🔧 Starting infrastructure services..."
    INFRA_SERVICES="nexent-elasticsearch nexent-postgresql nexent-minio redis"
    
    # Add openssh-server if Terminal tool is enabled
    if [ "$ENABLE_TERMINAL_TOOL" = "true" ]; then
      INFRA_SERVICES="$INFRA_SERVICES nexent-openssh-server"
      echo "🔧 Terminal tool enabled - openssh-server will be included in infrastructure"
    fi

    if ! docker-compose -p nexent -f "docker-compose${COMPOSE_FILE_SUFFIX}" up -d $INFRA_SERVICES; then
      echo "❌ ERROR Failed to start infrastructure services"
      exit 1
    fi
    
    # Install Supabase services based on deployment version
    install_supabase_services || {
      echo "❌ ERROR Supabase services installation failed"
      exit 1
    }
    
    # Wait for services to be healthy, then generate complete environment
    echo "🔑 Generating complete environment file with all keys..."
    generate_env_for_infrastructure || { echo "❌ Environment generation failed"; exit 1; }
    
    echo "🎉  Infrastructure deployment completed successfully!"
    if [ "$ENABLE_TERMINAL_TOOL" = "true" ]; then
      echo "🔧 Terminal tool (openssh-server) is now available for AI agents"
    fi
    echo "📦  You can now start the core services manually using dev containers"
    echo "📁  Environment file available at: $(cd .. && pwd)/.env"
    echo "💡  Use 'source .env' to load environment variables in your development shell"
    return 0
  fi

  # Install services and generate environment
  install || { echo "❌ Service installation failed"; exit 1; }
  clean
  # echo "Creating admin user..."
  # docker exec -d nexent bash -c "curl -X POST http://kong:8000/auth/v1/signup -H \"apikey: ${SUPABASE_KEY}\" -H \"Authorization: Bearer ${SUPABASE_KEY}\" -H \"Content-Type: application/json\" -d '{\"email\":\"admin@example.com\",\"password\":\"123123\",\"email_confirm\":true,\"data\":{\"role\":\"admin\"}}'"

  echo "🎉  Deployment completed successfully!"
  echo "🌐  You can now access the application at http://localhost:3000"
}

# Execute main deployment with error handling
if ! main_deploy; then
  echo "❌ Deployment failed. Please check the error messages above and try again."
  exit 1
fi
