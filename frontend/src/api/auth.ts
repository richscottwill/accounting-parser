/**
 * Auth API calls for the accounting-parser frontend.
 *
 * Uses @simplewebauthn/browser to drive the WebAuthn ceremonies — it takes
 * the `publicKey` options struct returned by the backend and calls
 * `navigator.credentials.create` / `navigator.credentials.get` with proper
 * base64url encoding of byte fields.
 *
 * The backend expects base64 fields; SimpleWebAuthn emits base64url, and
 * the backend's `_b64d` helper accepts both.
 */
import {
  startAuthentication,
  startRegistration,
} from "@simplewebauthn/browser";
import { api, setSessionToken } from "./client";

export interface SignupBeginRequest {
  firm_name: string;
  admin_email: string;
  admin_ptin?: string | null;
}

export interface SignupBeginResponse {
  tenant_id: string;
  firm_id: string;
  user_id: string;
  registration_options: { publicKey: PublicKeyCredentialCreationOptionsJSON };
  signup_token: string;
}

export interface MeResponse {
  user_id: string;
  tenant_id: string;
  firm_id: string | null;
  role: string;
  email: string;
}

// SimpleWebAuthn type aliases (the library re-exports these from its types pkg).
type PublicKeyCredentialCreationOptionsJSON =
  import("@simplewebauthn/browser").PublicKeyCredentialCreationOptionsJSON;
type PublicKeyCredentialRequestOptionsJSON =
  import("@simplewebauthn/browser").PublicKeyCredentialRequestOptionsJSON;

/**
 * Complete a full signup: create tenant/firm, enroll a passkey, receive session JWT.
 *
 * @throws on any failure; the caller should surface the message to the user.
 */
export async function performSignup(req: SignupBeginRequest): Promise<MeResponse> {
  const begin = await api.post<SignupBeginResponse>("/auth/signup/begin", req);
  const options = begin.data.registration_options.publicKey;

  const reg = await startRegistration({ optionsJSON: options });

  const complete = await api.post<{ session_token: string }>(
    "/auth/signup/complete",
    {
      signup_token: begin.data.signup_token,
      client_data_json_b64: reg.response.clientDataJSON,
      attestation_object_b64: reg.response.attestationObject,
    }
  );
  setSessionToken(complete.data.session_token);
  return fetchMe();
}

export async function performLogin(email: string): Promise<MeResponse> {
  const begin = await api.post<{
    assertion_options: { publicKey: PublicKeyCredentialRequestOptionsJSON };
    login_token: string;
  }>("/auth/login/begin", { email });

  const assertion = await startAuthentication({
    optionsJSON: begin.data.assertion_options.publicKey,
  });

  const complete = await api.post<{ session_token: string }>(
    "/auth/login/complete",
    {
      login_token: begin.data.login_token,
      credential_id_b64: assertion.id,
      client_data_json_b64: assertion.response.clientDataJSON,
      authenticator_data_b64: assertion.response.authenticatorData,
      signature_b64: assertion.response.signature,
    }
  );
  setSessionToken(complete.data.session_token);
  return fetchMe();
}

export async function fetchMe(): Promise<MeResponse> {
  const r = await api.get<MeResponse>("/auth/me");
  return r.data;
}

export function logout(): void {
  setSessionToken(null);
}
