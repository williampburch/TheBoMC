# Azure VM Deployment Guide

This guide assumes:

- Azure Ubuntu VM
- Docker Engine and Docker Compose on the VM
- This repo deployed on the VM
- Domain pointed at the VM public IP

## 1. Create Azure resources

Official Azure CLI references:

- VM creation: https://learn.microsoft.com/en-us/azure/virtual-machines/linux/quick-create-cli
- Full Linux VM setup: https://learn.microsoft.com/en-us/azure/virtual-machines/linux/create-cli-complete

Example Cloud Shell session:

```bash
RG=bomc-rg
LOCATION=eastus
VM=bomc-vm
ADMIN_USER=azureuser

az group create --name $RG --location $LOCATION

az vm create \
  --resource-group $RG \
  --name $VM \
  --image Ubuntu2204 \
  --size Standard_B2s \
  --admin-username $ADMIN_USER \
  --generate-ssh-keys \
  --public-ip-sku Standard
```

Open only the required ports:

```bash
az vm open-port --resource-group $RG --name $VM --port 22
az vm open-port --resource-group $RG --name $VM --port 80
az vm open-port --resource-group $RG --name $VM --port 443
```

Get the public IP:

```bash
az vm show --show-details --resource-group $RG --name $VM --query publicIps --output tsv
```

## 2. Connect to the VM

```bash
ssh azureuser@<vm-public-ip>
```

## 3. Install Docker and Compose on Ubuntu

Docker docs can change. Use the current official Docker Engine install guide for Ubuntu:

- https://docs.docker.com/engine/install/ubuntu/

At a minimum, verify:

```bash
docker --version
docker compose version
```

## 4. Pull the repo onto the VM

```bash
git clone https://github.com/williampburch/TheBoMC.git
cd TheBoMC
```

Or if you already copied the repo some other way, just `cd` into it.

## 5. Create the production environment file

```bash
cp .env.example .env
```

Minimum production values:

```env
SECRET_KEY=<long-random-secret>
DATABASE_URL=sqlite:////app/instance/buffet_club.db
ADMIN_EMAIL=<your-admin-email>
ADMIN_PASSWORD=<strong-password>
ADMIN_NAME=<your-name>
```

If you move to Azure Database for PostgreSQL later, replace `DATABASE_URL` with the Postgres connection string.

## 6. Start the app stack

```bash
docker compose up -d --build
```

Check status:

```bash
docker compose ps
docker compose logs web --tail 100
docker compose logs nginx --tail 100
```

## 7. Run database migrations

Run the initial schema migration:

```bash
docker compose exec web flask --app app:app db upgrade
```

If needed, seed the first admin by restarting after `.env` is in place:

```bash
docker compose restart web
```

## 8. Test HTTP before enabling TLS

Visit:

```text
http://<vm-public-ip>
```

At this stage, Nginx should proxy to the Flask app over port 80.

## 9. Point your domain to the VM

Create DNS records for your chosen domain:

- `A` record for `@`
- `A` record for `www` if you want it

Both should point at the VM public IP.

Wait for DNS to resolve before requesting a certificate.

## 10. Issue a Let's Encrypt certificate

The repo already mounts the ACME challenge directory and Let's Encrypt storage into the Nginx and Certbot containers.

Example command:

```bash
docker compose run --rm --service-ports certbot certonly \
  --webroot \
  --webroot-path /var/www/certbot \
  --email you@example.com \
  --agree-tos \
  --no-eff-email \
  -d example.com \
  -d www.example.com
```

## 11. Enable TLS in Nginx

Copy the example TLS config:

```bash
cp nginx/conf.d/tls.conf.example nginx/conf.d/tls.conf
```

Edit `nginx/conf.d/tls.conf`:

- Replace `example.com` with your real domain
- Replace the certificate paths if needed so they match your domain directory under `/etc/letsencrypt/live/`

Then reload Nginx:

```bash
docker compose restart nginx
```

## 12. Renew certificates

Run periodically, for example from cron or a systemd timer:

```bash
docker compose run --rm certbot renew
docker compose restart nginx
```

## 13. Operational checks

Useful commands:

```bash
docker compose ps
docker compose logs -f web
docker compose logs -f nginx
docker exec -it bomc-web /bin/sh
```

## 14. Hardening ideas for AZ-104 practice

Good follow-up tasks:

- Use a static public IP
- Restrict SSH source IPs in the NSG
- Move backups to Azure Storage
- Put the VM behind Azure Bastion instead of exposing port 22 broadly
- Attach a data disk if you want cleaner separation for persistent app data
- Use Azure Monitor / Log Analytics for guest and container visibility
