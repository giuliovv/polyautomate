'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { configureAuth, isAuthenticated } from '@/lib/auth';

interface AuthProviderProps {
  children: React.ReactNode;
}

export function AuthProvider({ children }: AuthProviderProps) {
  const router = useRouter();
  const [isReady, setIsReady] = useState(false);

  useEffect(() => {
    // Configure Amplify on mount
    configureAuth();

    // Check if user is authenticated
    isAuthenticated().then((authed) => {
      if (!authed) {
        router.push('/login');
      } else {
        setIsReady(true);
      }
    });
  }, [router]);

  if (!isReady) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="text-muted-foreground">Loading...</div>
      </div>
    );
  }

  return <>{children}</>;
}
