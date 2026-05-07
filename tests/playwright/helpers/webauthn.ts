import type { BrowserContext, CDPSession, Page } from "@playwright/test";

async function addVirtualAuthenticator(cdp: CDPSession) {
  await cdp.send("WebAuthn.enable", { enableUI: false });
  const { authenticatorId } = await cdp.send("WebAuthn.addVirtualAuthenticator", {
    options: {
      protocol: "ctap2",
      transport: "internal",
      hasResidentKey: true,
      hasUserVerification: true,
      isUserVerified: true,
      automaticPresenceSimulation: true,
    },
  });
  return authenticatorId;
}

/**
 * Enable a virtual WebAuthn authenticator on the given Chromium context.
 *
 * WebAuthn.enable is per-target. Tests that create additional pages after
 * this call must use `attachVirtualAuthenticatorToPage` on each new page.
 */
export async function enableVirtualAuthenticator(
  context: BrowserContext
): Promise<{ cdp: CDPSession; authenticatorId: string }> {
  const page: Page = context.pages()[0] ?? (await context.newPage());
  const cdp = await context.newCDPSession(page);
  const authenticatorId = await addVirtualAuthenticator(cdp);
  return { cdp, authenticatorId };
}

/**
 * Attach a virtual WebAuthn authenticator to a specific page.
 *
 * Prefer this over `enableVirtualAuthenticator` when the test creates the
 * page explicitly — guarantees the authenticator is wired to exactly the
 * target the test will drive.
 */
export async function attachVirtualAuthenticatorToPage(
  page: Page
): Promise<{ cdp: CDPSession; authenticatorId: string }> {
  const cdp = await page.context().newCDPSession(page);
  const authenticatorId = await addVirtualAuthenticator(cdp);
  return { cdp, authenticatorId };
}

export async function clearVirtualAuthenticator(
  cdp: CDPSession,
  authenticatorId: string
): Promise<void> {
  await cdp.send("WebAuthn.removeVirtualAuthenticator", { authenticatorId });
  await cdp.detach();
}
