// PM2 process config for the SDRC DEXA worker services.
// Deploy: pm2 start ecosystem.config.js
// On Ubuntu: cd /opt/sdrc/sdrc-dexa-worker && pm2 start ecosystem.config.js --env production

module.exports = {
  apps: [
    {
      name:        'sdrc-collector-api',
      script:      'collector_api.py',
      interpreter: 'python3',
      cwd:         '/opt/sdrc/sdrc-dexa-worker/worker',
      env_production: {
        // MDB_PATH and XPS_WATCH_DIR come from the .env file in the cwd
      },
      // Restart on crash; don't restart if it exits cleanly
      autorestart: true,
      max_restarts: 10,
      restart_delay: 3000,
      // Stream logs to pm2 log folder
      out_file:  '/var/log/sdrc/collector-api.log',
      error_file: '/var/log/sdrc/collector-api-err.log',
      merge_logs: true,
    },
  ],
}
