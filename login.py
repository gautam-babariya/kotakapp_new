import os
from dotenv import load_dotenv
import pyotp
from neo_api_client import NeoAPI

# Load environment variables from the .env file
load_dotenv()

def get_authenticated_client():
    """Generates TOTP, initializes the NeoAPI client, logs in, and validates via MPIN."""
    try:
        # Generate the current 6-digit TOTP code using the 16-character secret
        totp_secret = os.getenv("KOTAK_TOTP_SECRET")
        if not totp_secret:
            raise ValueError("KOTAK_TOTP_SECRET is missing in your environment variables.")
        
        totp_code = pyotp.TOTP(totp_secret).now()

        # Initialize the client using environment variables
        client = NeoAPI(
            consumer_key=os.getenv("KOTAK_CONSUMER_KEY"),
            environment="prod",
            access_token=None,
            neo_fin_key=None,
        )

        # Step 1: Login with dynamically generated TOTP
        login_response = client.totp_login(
            mobile_number=os.getenv("KOTAK_MOBILE_NUMBER"),
            ucc=os.getenv("KOTAK_UCC"),
            totp=totp_code,
        )

        # Step 2: Validate with MPIN to complete authentication
        validate_response = client.totp_validate(
            mpin=os.getenv("KOTAK_MPIN")
        )
        print("Successfully authenticated with Kotak Neo API.")
        return client

    except Exception as e:
        print(f"Authentication failed: {e}")
        return None