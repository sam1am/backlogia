# legendary_wrapper.py
import subprocess
import json
import sys


def is_legendary_installed():
    """Check if Legendary CLI is installed and accessible."""
    try:
        result = subprocess.run(
            ["legendary", "--version"],
            capture_output=True,
            text=True
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def check_authentication():
    """Check if user is authenticated with Epic Games via Legendary.

    Returns:
        tuple: (is_authenticated: bool, username: str or None, error: str or None)
    """
    try:
        result = subprocess.run(
            ["legendary", "status", "--json"],
            capture_output=True,
            text=True
        )

        # Check for corrective action errors (privacy policy, etc.)
        output = result.stdout + result.stderr
        if "corrective_action_required" in output or "PRIVACY_POLICY" in output:
            return False, None, "corrective_action"

        if result.returncode != 0:
            return False, None, None

        # Parse the status output
        for line in result.stdout.strip().split('\n'):
            if line:
                try:
                    data = json.loads(line)
                    account = data.get("account")
                    # Check for actual login - "<not logged in>" means not authenticated
                    if account and account != "<not logged in>":
                        return True, account, None
                except json.JSONDecodeError:
                    continue

        return False, None, None
    except FileNotFoundError:
        return False, None, None


def authenticate():
    """Guide user through Epic Games authentication.

    Returns:
        bool: True if authentication successful, False otherwise
    """
    print("\n" + "=" * 60)
    print("Epic Games Authentication Required")
    print("=" * 60)
    print("\nYou need to log in to your Epic Games account.")
    print("\nAuthentication options:")
    print("  1. Browser login (recommended) - Opens Epic login in browser")
    print("  2. Authorization code - Manually enter code from Epic website")
    print("  3. Import from Epic Games Launcher - Use existing EGL credentials")
    print("  4. Cancel")

    while True:
        choice = input("\nSelect option (1-4): ").strip()

        if choice == "1":
            return _auth_browser()
        elif choice == "2":
            return _auth_code()
        elif choice == "3":
            return _auth_import()
        elif choice == "4":
            print("Authentication cancelled.")
            return False
        else:
            print("Invalid option. Please enter 1, 2, 3, or 4.")


def _auth_browser():
    """Authenticate using browser-based login."""
    print("\nAttempting browser-based login...")
    print("A browser window should open for Epic Games login.")
    print("If it doesn't open automatically, use option 2 instead.\n")

    result = subprocess.run(
        ["legendary", "auth"],
        capture_output=False
    )

    if result.returncode == 0:
        print("\nAuthentication successful!")
        return True
    else:
        print("\nBrowser authentication failed.")
        print("Try using authorization code method (option 2) instead.")
        return False


def _auth_code():
    """Authenticate using authorization code."""
    print("\nTo get your authorization code:")
    print("  1. Open: https://legendary.gl/epiclogin")
    print("  2. Log in to your Epic Games account")
    print("  3. Copy the 'authorizationCode' value from the JSON response")

    code = input("\nEnter authorization code (or 'cancel' to go back): ").strip()

    if code.lower() == 'cancel':
        return False

    if not code:
        print("No code entered.")
        return False

    result = subprocess.run(
        ["legendary", "auth", "--code", code],
        capture_output=True,
        text=True
    )

    if result.returncode == 0:
        print("\nAuthentication successful!")
        return True
    else:
        print(f"\nAuthentication failed: {result.stderr or 'Unknown error'}")
        return False


def _auth_import():
    """Import credentials from Epic Games Launcher."""
    print("\nImporting credentials from Epic Games Launcher...")
    print("WARNING: This will log you out of the Epic Games Launcher!")

    confirm = input("Continue? (yes/no): ").strip().lower()

    if confirm != 'yes':
        print("Import cancelled.")
        return False

    result = subprocess.run(
        ["legendary", "auth", "--import"],
        capture_output=True,
        text=True
    )

    if result.returncode == 0:
        print("\nCredentials imported successfully!")
        return True
    else:
        print(f"\nImport failed: {result.stderr or 'Epic Games Launcher may not be installed'}")
        return False


def _parse_game(game):
    """Parse a game object from legendary JSON into our format."""
    metadata = game.get("metadata", {})

    # Extract supported platforms from releaseInfo
    platforms = []
    release_info = metadata.get("releaseInfo", [])
    if release_info:
        platforms = release_info[0].get("platform", [])

    # Extract images by type
    images = {}
    for img in metadata.get("keyImages", []):
        img_type = img.get("type", "unknown")
        images[img_type] = {
            "url": img.get("url"),
            "width": img.get("width"),
            "height": img.get("height")
        }

    # Get the best available cover image
    cover_image = None
    for img_type in ["DieselGameBoxTall", "DieselGameBox", "Thumbnail"]:
        if img_type in images:
            cover_image = images[img_type]["url"]
            break

    return {
        "name": game.get("app_title") or metadata.get("title"),
        "app_name": game.get("app_name"),
        "sku": metadata.get("id"),
        "namespace": metadata.get("namespace"),
        "description": metadata.get("description"),
        "developer": metadata.get("developer"),
        "supported_platforms": platforms,
        "cover_image": cover_image,
        "images": images,
        "dlcs": game.get("dlcs", []),
        "can_run_offline": metadata.get("customAttributes", {}).get("CanRunOffline", {}).get("value") == "true",
        "created_date": metadata.get("creationDate"),
        "last_modified": metadata.get("lastModifiedDate"),
        "store": "epic"
    }


def _handle_corrective_action():
    """Handle corrective action required error (e.g., privacy policy acceptance)."""
    print("\n" + "=" * 60)
    print("Epic Games Account Action Required")
    print("=" * 60)
    print("\nEpic Games requires you to accept updated terms or privacy policy.")
    print("You need to log out and log back in through a browser to proceed.")
    print("\nWould you like to log out now?")

    choice = input("Log out and re-authenticate? (yes/no): ").strip().lower()

    if choice == 'yes':
        logout()
        print("\nPlease authenticate again to accept the updated terms.")
        return authenticate()
    else:
        print("Please run with --logout and then re-run to authenticate.")
        return False


def get_epic_library_legendary():
    """Get full Epic library using Legendary CLI.

    Returns:
        list: List of game dictionaries, or None if not authenticated
    """
    # Check if Legendary is installed
    if not is_legendary_installed():
        print("Legendary not installed. Run: pip install legendary-gl")
        return None

    # Check authentication status
    is_auth, username, error = check_authentication()

    if error == "corrective_action":
        if not _handle_corrective_action():
            return None
        # Re-check after handling
        is_auth, username, error = check_authentication()
        if not is_auth:
            print("Authentication failed after corrective action.")
            return None

    if not is_auth:
        print("Not logged in to Epic Games.")
        if not authenticate():
            return None

        # Verify authentication succeeded
        is_auth, username, error = check_authentication()
        if error == "corrective_action":
            if not _handle_corrective_action():
                return None
            is_auth, username, error = check_authentication()
        if not is_auth:
            print("Authentication verification failed.")
            return None

    print(f"Logged in as: {username}")
    print("Fetching Epic Games library...")

    try:
        result = subprocess.run(
            ["legendary", "list", "--json"],
            capture_output=True,
            text=True
        )

        # Check for corrective action in list command too
        output = result.stdout + result.stderr
        if "corrective_action_required" in output or "PRIVACY_POLICY" in output:
            print("\nEpic Games requires you to accept updated terms.")
            if _handle_corrective_action():
                # Retry the list command
                result = subprocess.run(
                    ["legendary", "list", "--json"],
                    capture_output=True,
                    text=True
                )
            else:
                return None

        if result.returncode != 0:
            print(f"Error fetching library: {result.stderr}")
            return []

        # Parse JSON output - legendary outputs a JSON array
        games = []
        try:
            data = json.loads(result.stdout)
            # Handle both array format and line-delimited format
            if isinstance(data, list):
                for game in data:
                    games.append(_parse_game(game))
            else:
                # Single object
                games.append(_parse_game(data))
        except json.JSONDecodeError:
            # Try line-delimited JSON as fallback
            for line in result.stdout.strip().split('\n'):
                if line:
                    try:
                        game = json.loads(line)
                        games.append(_parse_game(game))
                    except json.JSONDecodeError:
                        continue

        return games
    except Exception as e:
        print(f"Error: {e}")
        return []


def logout():
    """Log out from Epic Games account."""
    result = subprocess.run(
        ["legendary", "auth", "--delete"],
        capture_output=True,
        text=True
    )

    if result.returncode == 0:
        print("Successfully logged out from Epic Games.")
        return True
    else:
        print(f"Logout failed: {result.stderr}")
        return False


if __name__ == "__main__":
    # Handle command line arguments
    if len(sys.argv) > 1:
        if sys.argv[1] == "--logout":
            logout()
            sys.exit(0)
        elif sys.argv[1] == "--status":
            is_auth, username, error = check_authentication()
            if error == "corrective_action":
                print("Logged in but action required (e.g., accept privacy policy)")
                print("Run: python epic.py --logout  then re-authenticate")
            elif is_auth:
                print(f"Logged in as: {username}")
            else:
                print("Not logged in")
            sys.exit(0)
        elif sys.argv[1] == "--debug":
            # Print raw JSON response from legendary
            if not is_legendary_installed():
                print("Legendary not installed.")
                sys.exit(1)
            is_auth, username, error = check_authentication()
            if not is_auth:
                print("Not logged in. Run: python epic.py to authenticate")
                sys.exit(1)
            result = subprocess.run(
                ["legendary", "list", "--json"],
                capture_output=True,
                text=True
            )
            data = json.loads(result.stdout)
            # Print first game's full structure
            if data:
                print("=== First game raw JSON ===")
                print(json.dumps(data[0], indent=2))
                print("\n=== Available top-level keys ===")
                print(list(data[0].keys()))
            sys.exit(0)
        elif sys.argv[1] == "--help":
            print("Epic Games Library Exporter (using Legendary)")
            print("\nUsage: python epic.py [option]")
            print("\nOptions:")
            print("  (no args)   Export library to epic_library.json")
            print("  --status    Check login status")
            print("  --logout    Log out from Epic Games")
            print("  --debug     Show raw JSON structure from first game")
            print("  --help      Show this help message")
            sys.exit(0)

    library = get_epic_library_legendary()

    if library is None:
        print("Failed to retrieve library.")
        sys.exit(1)

    with open("epic_library.json", "w") as f:
        json.dump(library, f, indent=2)
    print(f"Exported {len(library)} Epic games to epic_library.json")
