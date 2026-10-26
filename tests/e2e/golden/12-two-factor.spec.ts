// Golden path 12 (docs/specs/01-harness.md): two-factor sign-in with an authenticator app (TOTP).
//
// The feature does not exist yet: only the dormant User.totp_* columns do, and no view, URL or login
// step reads them. Phase 4 builds it. Until then this is the suite's one declared pending test, so
// Phase 4 starts from a red test and the gate counts it as pending, never as passing. Its steps are
// written out below; Phase 4 turns each comment into code against the new screens, using data-testid
// hooks and database probes like every other golden path.
import { test } from '../support/test';

const PENDING = 'TOTP 2FA ships in Phase 4';

test.fixme(
  'owner turns on two-factor sign-in, signs out, signs back in with a code; an owner without it is prompted',
  { annotation: { type: 'fixme', description: PENDING } },
  async () => {
    // Pending: TOTP 2FA ships in Phase 4.
    //
    // Enable TOTP (owner of workspace A, signed in with as('owner')):
    // 1. Open the account security page and choose to turn on two-factor sign-in; axe on the page.
    // 2. The page shows a QR code and the setup key; a probe returns the pending secret, and the test
    //    computes the current six-digit code from it (RFC 6238, 30-second step, SHA-1).
    // 3. Enter the code and confirm; axe on the confirmation with the recovery codes.
    // 4. Probe: the user's TOTP device is confirmed and recovery codes exist (stored hashed, never
    //    returned in full by the probe).
    //
    // Sign out and back in with a code:
    // 5. Sign out (the base.html sign-out control); the session is gone (probe: no session for the user).
    // 6. Post the login form with the owner's email and password (call reset_login_limits first):
    //    the second step asks for a code and no session is signed in yet (probe).
    // 7. A wrong code stays on the code step with a message and no session.
    // 8. The current code lands on Home of workspace A; probe: the session belongs to the owner and
    //    records that the second factor was used.
    // 9. A used recovery code works once and is spent (probe).
    //
    // An owner without two-factor is prompted:
    // 10. A fresh organisation owner without TOTP (a fixture) signs in and is prompted to turn it on
    //     (Home shows the prompt, or the sign-in lands on the setup step), and can follow it to step 1.
    // 11. An editor without TOTP is not prompted, if Phase 4 keeps the prompt to owners.
    //
    // Every screen reached and every dialog opened is checked with axe; the probe refused_network
    // lists no outside host.
  },
);
