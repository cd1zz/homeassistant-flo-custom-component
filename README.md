# Flo by Moen (OAuth2 Support)

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![GitHub Release](https://img.shields.io/github/release/cd1zz/flo-custom-component.svg?style=flat-square)](https://github.com/cd1zz/flo-custom-component/releases)

Custom component for Home Assistant that adds **OAuth2 support** for Flo by Moen smart water monitoring and shutoff devices.

## Why This Custom Component?

**Moen changed their API from simple authentication to OAuth2 in late 2024/early 2025**, breaking the built-in Home Assistant integration. This custom component:

✅ Supports the **new OAuth2 authentication flow**
✅ Works with current Moen API endpoints
✅ Maintains all original integration features
✅ Automatically refreshes tokens
✅ Drop-in replacement for the built-in integration

## Features

- **Full OAuth2 Support** - Uses Moen's current authentication system
- **Automatic Token Refresh** - Access tokens auto-refresh before expiry
- **Water Monitoring** - Flow rate, pressure, temperature, humidity sensors
- **Leak Detection** - Binary sensors for water detection (leak detectors)
- **Valve Control** - Open/close main water valve
- **Location Modes** - Set home, away, and sleep modes
- **Health Tests** - Run system health tests
- **Daily Consumption** - Track daily water usage

## Installation

### HACS (Recommended)

1. Open **HACS** in Home Assistant
2. Click the **3 dots** in the top right
3. Select **Custom repositories**
4. Add repository URL: `https://github.com/cd1zz/flo-custom-component`
5. Category: **Integration**
6. Click **Add**
7. Click **Install**
8. Restart Home Assistant

### Manual Installation

1. **Download** the latest release from [releases page](https://github.com/cd1zz/flo-custom-component/releases)
2. **Extract** the `custom_components/flo` folder
3. **Copy** to your Home Assistant `config/custom_components/` directory:
   ```
   config/
   └── custom_components/
       └── flo/
           ├── __init__.py
           ├── api.py
           ├── manifest.json
           └── ... (all other files)
   ```
4. **Restart** Home Assistant

### Git Clone Method

```bash
# SSH into Home Assistant (or use VS Code add-on terminal)
cd /config/custom_components

# Clone the repository
git clone https://github.com/cd1zz/flo-custom-component.git flo

# Restart Home Assistant
ha core restart
```

## Configuration

### Step 1: Remove Built-in Integration (if installed)

1. Go to **Settings** → **Devices & Services**
2. Find **Flo by Moen**
3. Click **three dots** → **Delete**

### Step 2: Add Custom Integration

1. Go to **Settings** → **Devices & Services**
2. Click **+ Add Integration**
3. Search for **Flo**
4. Enter your Moen account credentials
5. Integration will authenticate using OAuth2

### Step 3: Verify

Check logs for successful authentication:
```
Configuration → Settings → Logs → Filter: "flo"
```

You should see:
```
Authentication successful, token expires in 86400 seconds
```

## Supported Devices

- **Flo Smart Water Monitor and Shutoff** - Main water line monitor with shutoff valve
- **Flo by Moen Smart Water Detector** - Leak detection pucks

## Entities Created

### Sensors
- **Flow Rate** (GPM) - Current water flow
- **Water Pressure** (PSI) - Current water pressure
- **Temperature** (°F) - Water temperature
- **Humidity** (%) - Ambient humidity
- **Daily Consumption** (gallons) - Total water used today

### Binary Sensors
- **Pending Alerts** - Critical/warning/info alerts
- **Water Detected** - Leak detector status (leak detector only)

### Switch
- **Shutoff Valve** - Open/close main water valve

### Services

#### `flo.set_home_mode`
Set location to home mode (normal monitoring)

#### `flo.set_away_mode`
Set location to away mode (sensitive leak detection)

#### `flo.set_sleep_mode`
Set location to sleep mode (reduced sensitivity)
- `sleep_minutes`: Duration in minutes (60-720)
- `revert_to_mode`: Mode to return to (home/away)

#### `flo.run_health_test`
Run system health test on the device

## Troubleshooting

### Integration Not Found After Installation

1. Verify files are in `/config/custom_components/flo/`
2. Check `manifest.json` exists
3. Restart Home Assistant
4. Clear browser cache

### Authentication Fails

1. Verify credentials work in Moen mobile app
2. Check Home Assistant logs for detailed error
3. Ensure internet connectivity
4. Try removing and re-adding integration

### "Invalid Token" Errors

This should NOT happen with OAuth2, but if it does:
1. Remove integration
2. Restart Home Assistant
3. Re-add integration
4. Check logs for token refresh errors

### Entities Not Updating

1. Check device is online in Moen app
2. Verify internet connectivity
3. Check Home Assistant logs for API errors
4. Integration updates every 60 seconds

### Enable Debug Logging

Add to `configuration.yaml`:
```yaml
logger:
  default: info
  logs:
    custom_components.flo: debug
```

Then restart and check logs: **Settings → System → Logs**

## Technical Details

### OAuth2 Flow

This integration uses **OAuth2 Password Grant** flow:

1. User provides username/password
2. Integration exchanges credentials for access_token + refresh_token
3. Access tokens expire in 24 hours
4. Integration auto-refreshes 5 minutes before expiry
5. Refresh tokens are long-lived (~92 years)

### API Endpoints

```
Authentication:  POST /api/v1/oauth2/token
User Info:       GET  /api/v2/users/{id}?expand=locations
Device Info:     GET  /api/v2/devices/{id}
Valve Control:   POST /api/v2/devices/{id}
Location Modes:  POST /api/v2/locations/{id}/systemMode
```

### Client Credentials

OAuth2 client credentials (extracted from Moen mobile app):
- `client_id`: `3baec26f-0e8b-4e1d-84b0-e178f05ea0a5`
- `client_secret`: `3baec26f-0e8b-4e1d-84b0-e178f05ea0a5`

These are hardcoded in the integration and may need updating if Moen rotates them.

## Differences from Built-in Integration

### What Changed
- ✅ OAuth2 authentication (was: simple auth)
- ✅ Bearer token format (was: plain token)
- ✅ Automatic token refresh (was: manual token management)
- ✅ No external dependencies (was: `aioflo` library)

### What Stayed the Same
- ✅ All sensors and entities
- ✅ All services and features
- ✅ Configuration flow
- ✅ Device discovery

## FAQ

**Q: Will this be merged into Home Assistant Core?**
A: Hopefully! Once tested and stable, a PR can be submitted.

**Q: Will this break when HA updates?**
A: No, custom components override built-in ones. Updates to the built-in integration won't affect this.

**Q: Can I switch back to the built-in integration?**
A: Yes, just delete this custom component and restart HA.

**Q: Does this work with the Moen app?**
A: Yes! Both work simultaneously - same account, same API.

**Q: Are tokens stored securely?**
A: Yes, tokens are stored in memory only (not persisted to disk). You'll need to re-authenticate after HA restart (same as before).

## Contributing

Contributions welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## License

Apache License 2.0 - Same as Home Assistant Core

## Credits

- **Reverse Engineering**: OAuth2 flow captured from Moen mobile app
- **Original Integration**: Home Assistant Core team
- **OAuth2 Implementation**: Based on API traffic analysis

## Support

- **Issues**: [GitHub Issues](https://github.com/cd1zz/flo-custom-component/issues)
- **Discussions**: [GitHub Discussions](https://github.com/cd1zz/flo-custom-component/discussions)
- **Home Assistant Community**: [Community Forum](https://community.home-assistant.io)

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for version history.

---

**Note**: This is an unofficial custom component. Moen/Flo by Moen are trademarks of Moen Incorporated.
