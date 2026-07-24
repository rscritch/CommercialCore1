# CommercialCore GitHub Deployment

This package is organized for GitHub and Railway. Keep the folder structure intact.

## 1. Replace the flattened GitHub repository

The repository root must show folders such as `app`, `data`, `seed`, and `tests`.
Do not drag the contents of those folders individually into GitHub's browser uploader.

Recommended method:

1. Install and open GitHub Desktop.
2. Choose **File > Add local repository**.
3. Select this extracted `CommercialCore_GitHub_Deployment` folder.
4. If prompted, create a repository here.
5. Set the remote repository to your existing private `CommercialCore` repository.
6. Commit all files and push to `main`.

## 2. Railway service settings

Railway should detect the included `Dockerfile` and `railway.toml`. Remove any old manual
start command if Railway continues using it, because the deployment package supplies its own.

Add these Railway variables:

- `COMMERCIALCORE_ENV=production`
- `COMMERCIALCORE_DATA_DIR=/data`
- `COMMERCIALCORE_DATABASE_URL=sqlite:////data/commercialcore.db`
- `COMMERCIALCORE_SECRET=<long random value>`
- `COMMERCIALCORE_ADMIN_USERNAME=admin`
- `COMMERCIALCORE_ADMIN_PASSWORD=<strong private password>`
- `COMMERCIALCORE_ADMIN_FULL_NAME=CommercialCore Administrator`

Railway automatically supplies `PORT`.

## 3. Add persistent storage

In Railway, attach a volume to the CommercialCore service and mount it at:

`/data`

On the first deployment, `entrypoint.sh` copies the bundled four-client demonstration database
into the volume. Later deployments retain changes because the database lives on the volume.

## 4. Deploy and expose the service

Redeploy the latest GitHub commit. After the health check passes:

1. Open the service's **Settings**.
2. Under **Networking**, choose **Generate Domain**.
3. Open the generated URL.
4. Sign in with the administrator credentials stored in Railway Variables.

## Security note

This build is suitable for a controlled demonstration using synthetic data. Do not place real
customer or protected information in it until user isolation, backups, stronger authentication,
and a production database strategy have been implemented.
