import { Amplify } from 'aws-amplify';
import {
  signIn,
  signUp,
  signOut,
  confirmSignUp,
  getCurrentUser,
  fetchAuthSession,
} from 'aws-amplify/auth';

// Configure Amplify - values come from environment variables
export function configureAuth() {
  const userPoolId = process.env.NEXT_PUBLIC_COGNITO_USER_POOL_ID;
  const clientId = process.env.NEXT_PUBLIC_COGNITO_CLIENT_ID;
  const region = process.env.NEXT_PUBLIC_AWS_REGION || 'us-east-1';

  if (!userPoolId || !clientId) {
    console.warn('Cognito not configured - using dev mode');
    return;
  }

  Amplify.configure({
    Auth: {
      Cognito: {
        userPoolId,
        userPoolClientId: clientId,
        loginWith: {
          email: true,
        },
      },
    },
  });
}

// Sign up a new user
export async function cognitoSignUp(email: string, password: string) {
  const result = await signUp({
    username: email,
    password,
    options: {
      userAttributes: {
        email,
      },
    },
  });
  return result;
}

// Confirm sign up with verification code
export async function cognitoConfirmSignUp(email: string, code: string) {
  const result = await confirmSignUp({
    username: email,
    confirmationCode: code,
  });
  return result;
}

// Sign in
export async function cognitoSignIn(email: string, password: string) {
  const result = await signIn({
    username: email,
    password,
  });
  return result;
}

// Sign out
export async function cognitoSignOut() {
  await signOut();
}

// Get current user
export async function cognitoGetCurrentUser() {
  try {
    const user = await getCurrentUser();
    return user;
  } catch {
    return null;
  }
}

// Get JWT token for API calls (using ID token to include email claim)
export async function getAccessToken(): Promise<string | null> {
  try {
    const session = await fetchAuthSession();
    // Use idToken instead of accessToken to include email claim
    const token = session.tokens?.idToken?.toString();
    return token || null;
  } catch {
    return null;
  }
}

// Check if user is authenticated
export async function isAuthenticated(): Promise<boolean> {
  try {
    await getCurrentUser();
    return true;
  } catch {
    return false;
  }
}
