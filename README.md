# EcoBee---TPLink-SmartPlug-Control
Control TPLink smart plugs with EcoBee sensor data

heatrun.py is used to control multiple electric space heaters on TPLink smartplugs based on temperature data from EcoBee remote sensors.

You are solely responsible for safe operation of your space heaters.  In particular, ensure that your heaters are configured to turn themselves off at a safe high limit temperature.  Do not depend on this program to do so.  This program is not intended to be "fail safe" and may crash / exit with the smart plugs turned on.

The program will autodetect smart plugs with matching names - check code and update as needed to match your naming convention (please do not request to merge such changes into master).  This autodiscovery only works if run locally (inside LAN).

Supports text message push for issues / events -- must have Twilio account.

Integrates with Ohmconnect to respond to Ohmconnect events -- must have Ohmconnect account.

auth.py needs to be updated with keys -- ecobee developer api key, twilio keys & phone numbers, and ohmconnect URL.  You will need to set yourself up as a developer on the ecobee site to get the api key.

Before using heatrun.py for the first time, or if tokens have expired, use the new_tokens.py utility to issue EcoBee tokens and create / update the tokens.txt file where access and refresh tokens are stored.  The utility requests an authorization PIN, this is issued from the Ecobee customer portal (under the My Apps) section when you authorize a new app.

Once the tokens.txt file is created for the first time (with valid tokens), heatrun.py will refresh these tokens.
