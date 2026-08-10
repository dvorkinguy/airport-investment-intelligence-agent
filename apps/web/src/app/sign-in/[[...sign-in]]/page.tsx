import { notFound } from "next/navigation";
import { SignIn } from "@clerk/nextjs";
import { AuthShell } from "@/components/auth/AuthShell";
import { authAppearance } from "@/lib/clerk-appearance";
import { isClerkEnabled } from "@/lib/clerk-config";

export default function SignInPage() {
  // <SignIn> needs a ClerkProvider ancestor, which only mounts when Clerk is
  // enabled (see layout.tsx) - without this the route 500s in authless mode.
  if (!isClerkEnabled()) notFound();
  return (
    <AuthShell>
      <SignIn appearance={authAppearance} />
    </AuthShell>
  );
}
