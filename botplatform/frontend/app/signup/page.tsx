'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import {
  configureAuth,
  cognitoSignUp,
  cognitoConfirmSignUp,
  cognitoSignIn,
} from '@/lib/auth';

export default function SignupPage() {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [verificationCode, setVerificationCode] = useState('');
  const [step, setStep] = useState<'signup' | 'verify'>('signup');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    configureAuth();
  }, []);

  const handleSignup = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    if (password !== confirmPassword) {
      setError('Passwords do not match');
      return;
    }

    if (password.length < 8) {
      setError('Password must be at least 8 characters');
      return;
    }

    setLoading(true);

    try {
      const result = await cognitoSignUp(email, password);
      if (result.nextStep.signUpStep === 'CONFIRM_SIGN_UP') {
        setStep('verify');
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Signup failed';
      if (message.includes('UsernameExistsException')) {
        setError('An account with this email already exists');
      } else {
        setError(message);
      }
    } finally {
      setLoading(false);
    }
  };

  const handleVerify = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      await cognitoConfirmSignUp(email, verificationCode);
      // Auto sign in after verification
      await cognitoSignIn(email, password);
      router.push('/dashboard');
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Verification failed';
      if (message.includes('CodeMismatchException')) {
        setError('Invalid verification code');
      } else {
        setError(message);
      }
    } finally {
      setLoading(false);
    }
  };

  if (step === 'verify') {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="w-full max-w-md p-8">
          <h1 className="text-2xl font-bold text-center mb-6">Verify Email</h1>
          <p className="text-center text-muted-foreground mb-6">
            We sent a verification code to {email}
          </p>

          {error && (
            <div className="mb-4 p-3 rounded bg-destructive/10 text-destructive text-sm">
              {error}
            </div>
          )}

          <form onSubmit={handleVerify} className="space-y-4">
            <div>
              <label htmlFor="code" className="block text-sm font-medium mb-1">
                Verification Code
              </label>
              <input
                id="code"
                type="text"
                value={verificationCode}
                onChange={(e) => setVerificationCode(e.target.value)}
                className="w-full px-3 py-2 border rounded-md text-center text-2xl tracking-widest"
                placeholder="000000"
                maxLength={6}
                required
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full py-2 px-4 bg-primary text-primary-foreground rounded-md hover:bg-primary/90 disabled:opacity-50"
            >
              {loading ? 'Verifying...' : 'Verify'}
            </button>
          </form>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center">
      <div className="w-full max-w-md p-8">
        <h1 className="text-2xl font-bold text-center mb-6">Create Account</h1>

        {error && (
          <div className="mb-4 p-3 rounded bg-destructive/10 text-destructive text-sm">
            {error}
          </div>
        )}

        <form onSubmit={handleSignup} className="space-y-4">
          <div>
            <label htmlFor="email" className="block text-sm font-medium mb-1">
              Email
            </label>
            <input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full px-3 py-2 border rounded-md"
              required
            />
          </div>

          <div>
            <label htmlFor="password" className="block text-sm font-medium mb-1">
              Password
            </label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full px-3 py-2 border rounded-md"
              required
              minLength={8}
            />
          </div>

          <div>
            <label htmlFor="confirmPassword" className="block text-sm font-medium mb-1">
              Confirm Password
            </label>
            <input
              id="confirmPassword"
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              className="w-full px-3 py-2 border rounded-md"
              required
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2 px-4 bg-primary text-primary-foreground rounded-md hover:bg-primary/90 disabled:opacity-50"
          >
            {loading ? 'Creating account...' : 'Create Account'}
          </button>
        </form>

        <p className="mt-4 text-center text-sm text-muted-foreground">
          Already have an account?{' '}
          <Link href="/login" className="text-primary hover:underline">
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
