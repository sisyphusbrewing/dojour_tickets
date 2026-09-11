from playwright.sync_api import sync_playwright

def save_session():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        print("Opening DoJour...")
        page.goto("https://dojour.us/")

        input("\n>>> Log into DoJour in the opened browser window.\n>>> Once you see your dashboard, press [ENTER] here in terminal: ")

        context.storage_state(path="state.json")
        print("\nSession successfully saved to state.json!")
        browser.close()

if __name__ == "__main__":
    save_session()
