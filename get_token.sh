#!/bin/bash

# This script is used to get the token for the current user
# It will be used by the other scripts to authenticate with the API
# Get the token from the API
source .env
export POL_BAS=$(echo $POLAR_CLIENT_ID:$POLAR_CLIENT_SECRET| base64)

export code="38554f89006a2a81bb4baaba727d22a1"
echo -X POST https://polarremote.com/v2/oauth2/token \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -H 'Accept: application/json' \
  -H "Authorization: Basic $POL_BAS" \
  --data-urlencode "grant_type=authorization_code&code=Scode"

