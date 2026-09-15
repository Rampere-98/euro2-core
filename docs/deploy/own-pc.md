# Publicar desde tu propio PC (gratis)

El PC ya tiene todo (PostgreSQL en Docker, catálogo, servicio con scheduler). Solo hay que
exponerlo con HTTPS. Dos formas, ambas gratuitas y sin abrir puertos en el router.

## A. Dominio propio con Cloudflare Tunnel (recomendado)
1. Compra el dominio (p. ej. `euro2core.com`, ~10 €/año) en **Cloudflare Registrar**
   (dash.cloudflare.com → *Domain Registration*). Si ya lo tienes en otro registrador, añade el
   sitio a Cloudflare y apunta los *nameservers* a los que te indique.
2. Instala cloudflared: `winget install Cloudflare.cloudflared`.
3. Ejecuta (una vez; abre el navegador para autorizar tu cuenta):
   ```powershell
   powershell -ExecutionPolicy Bypass -File C:\Users\silas\Projects\euro2-core\scripts\cloudflare-tunnel.ps1 -Domain euro2core.com
   ```
   Crea el túnel, apunta el DNS (`@` y `www`) y lo instala como servicio de Windows.
4. Abre `https://euro2core.com/app/`, entra como administrador y en *Ajustes → Administración
   → Servidor* pon `https://euro2core.com` en "Orígenes permitidos".

## B. Sin dominio: Tailscale Funnel
`tailscale funnel --bg 8000` publica `https://<pc>.<tailnet>.ts.net`. Sirve para empezar; no
admite dominio propio.

## Servicio al iniciar Windows
`scripts\install-autostart.ps1` registra la tarea `euro2-core` (arranca al iniciar sesión y se
reinicia si se cae). Docker Desktop debe arrancar con Windows (Settings → General).

## Pasar después a un servidor (Oracle, etc.)
Sigue `oracle-free.md`; el DNS del dominio se cambia al nuevo servidor y el túnel se retira con
`cloudflare-tunnel.ps1 -Uninstall`.
