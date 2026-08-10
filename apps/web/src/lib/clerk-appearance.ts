/**
 * Shared Clerk `appearance` config so the SignIn/SignUp widgets match the
 * app's light analyst theme instead of Clerk's default purple. Values mirror
 * globals.css and the card styling used on the landing page (rounded-xl,
 * slate-200 borders, slate-900 primary).
 */
export const authAppearance = {
  variables: {
    colorPrimary: "#0f172a",
    colorPrimaryForeground: "#ffffff",
    colorBackground: "#ffffff",
    colorForeground: "#0f172a",
    colorInput: "#ffffff",
    colorInputForeground: "#0f172a",
    colorBorder: "#e2e8f0",
    colorMutedForeground: "#64748b",
    borderRadius: "0.75rem",
    fontFamily:
      '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif',
  },
};
