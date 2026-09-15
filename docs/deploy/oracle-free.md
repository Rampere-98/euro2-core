# Publicar Euro2 gratis: Oracle Cloud Always Free + DuckDNS

Coste total: 0 €. Tiempo: ~30 minutos la primera vez. Después, todo se administra desde la app.

## 1. Servidor (Oracle Cloud Always Free)
1. Crea una cuenta en <https://www.oracle.com/cloud/free/> (pide tarjeta solo para verificar;
   los recursos *Always Free* no se cobran).
2. *Compute → Instances → Create*: shape **VM.Standard.A1.Flex** (Ampere ARM), **4 OCPU,
   24 GB RAM**, imagen **Ubuntu 24.04**, disco de arranque 100 GB. Guarda la clave SSH.
   Si Oracle dice "Out of capacity", reintenta más tarde o en otro *availability domain*.
3. *Networking → Virtual Cloud Network → Security Lists → Default*: añade dos *Ingress rules*
   (source `0.0.0.0/0`, TCP, destination port **80** y **443**).

## 2. Dominio gratuito (DuckDNS)
1. Entra en <https://www.duckdns.org/> con GitHub/Google, crea el subdominio (p. ej. `euro2`) y
   pon la IP pública de la VM. Copia el **token**.

## 3. Instalar (un comando)
```bash
ssh ubuntu@IP-DE-LA-VM
curl -fsSL https://raw.githubusercontent.com/Rampere-98/euro2-core/main/deploy/install.sh | bash
```
Responde con el dominio (`euro2.duckdns.org`), el subdominio y el token de DuckDNS. El script
instala Docker, descarga el stack (`docker-compose.prod.yml`: base de datos, API con
scheduler, Caddy con HTTPS automático, DuckDNS, actualizador y copias nocturnas) y lo arranca.
La primera vez descarga la imagen (~2 GB) y los modelos locales (~1 GB): 5–10 minutos.

## 4. Primer arranque
1. Abre `https://euro2.duckdns.org/app/` y **regístrate**: la primera cuenta es la administradora.
2. *Ajustes → Administración*: pega tu clave de Numista (opcional), ajusta lo que quieras.
   Sin ninguna clave el catálogo ya se alimenta del BCE y los valores del modelo por tirada.

## 5. Llevar el catálogo que ya tienes (evita re-sincronizar)
En tu PC:
```bash
docker exec euro2-db pg_dump -U euro2 -Fc euro2 > euro2.dump
scp euro2.dump ubuntu@IP:/home/ubuntu/
rsync -a data/images/ ubuntu@IP:/home/ubuntu/images/
```
En la VM:
```bash
cd ~/euro2
sudo docker compose -f docker-compose.prod.yml stop api
sudo docker compose -f docker-compose.prod.yml exec -T db pg_restore -U euro2 -d euro2 --clean --if-exists --no-owner < ~/euro2.dump
sudo docker run --rm -v euro2_data:/data -v ~/images:/src alpine sh -c "mkdir -p /data/images && cp -r /src/. /data/images/"
sudo docker compose -f docker-compose.prod.yml start api
```
Luego, en la app, *Administración → Mantenimiento → Índice de fotos* e *Índice semántico*.

## 6. Actualizar
Cada `push` a `main` publica una imagen nueva en GHCR. En *Administración → Mantenimiento*
aparece "Hay una versión nueva" y el botón **Actualizar** la despliega (≈ 1 minuto).

## 7. Copias de seguridad
`backup` guarda un `pg_dump` diario en el volumen `euro2_backups` (14 días). Descarga una copia
completa cuando quieras desde *Administración → Mantenimiento*.

## Si prefieres tu propio PC
El mismo `docker-compose.prod.yml` funciona en cualquier máquina con Docker. Para exponerlo sin
abrir puertos usa un túnel gratuito (Cloudflare Tunnel) apuntando a `http://localhost:80`.
