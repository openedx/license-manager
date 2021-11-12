name="license_manager"
port="18170"

docker-compose up -d --build

# Install requirements
# Can be skipped right now because we're using the --build flag on docker-compose. This will need to be changed once we move to devstack.

# Wait for MySQL
echo "Waiting for MySQL"
until docker exec -i license_manager.mysql mysql -u root -se "SELECT EXISTS(SELECT 1 FROM mysql.user WHERE user = 'root')" &> /dev/null
do
  printf "."
  sleep 1
done
sleep 5

# Run migrations
echo -e "${GREEN}Running migrations for ${name}...${NC}"
docker exec -t license_manager.app bash -c "cd /edx/app/${name}/ && make migrate"

# Create development data
echo -e "${GREEN}Seeding development data..."
docker exec -t license_manager.app bash -c "python manage.py seed_development_data"

# Create superuser
echo -e "${GREEN}Creating super-user for ${name}...${NC}"
docker exec -t license_manager.app bash -c "echo 'from django.contrib.auth import get_user_model; User = get_user_model(); User.objects.create_superuser(\"edx\", \"edx@example.com\", \"edx\") if not User.objects.filter(username=\"edx\").exists() else None' | python /edx/app/${name}/manage.py shell"

# Provision IDA User in LMS
echo -e "${GREEN}Provisioning ${name}_worker in LMS...${NC}"
docker exec -t edx.devstack.lms  bash -c "source /edx/app/edxapp/edxapp_env && python /edx/app/edxapp/edx-platform/manage.py lms --settings=devstack_docker manage_user ${name}_worker ${name}_worker@example.com --staff --superuser"

# Create the DOT applications - one for single sign-on and one for backend service IDA-to-IDA authentication.
docker exec -t edx.devstack.lms  bash -c "source /edx/app/edxapp/edxapp_env && python /edx/app/edxapp/edx-platform/manage.py lms --settings=devstack_docker create_dot_application --grant-type authorization-code --skip-authorization --redirect-uris 'http://localhost:${port}/complete/edx-oauth2/' --client-id '${name}-sso-key' --client-secret '${name}-sso-secret' --scopes 'user_id' ${name}-sso ${name}_worker"
docker exec -t edx.devstack.lms bash -c "source /edx/app/edxapp/edxapp_env && python /edx/app/edxapp/edx-platform/manage.py lms --settings=devstack_docker create_dot_application --grant-type client-credentials --client-id '${name}-backend-service-key' --client-secret '${name}-backend-service-secret' ${name}-backend-service ${name}_worker"

# Restart container
docker-compose restart app
