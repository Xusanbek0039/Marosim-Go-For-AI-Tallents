import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";

import { Providers } from "@/components/providers";

import "./globals.css";

const jakarta = localFont({
  src: "./fonts/jakarta-latin.woff2",
  variable: "--font-jakarta",
  weight: "400 800",
  display: "swap",
});

export const metadata: Metadata = {
  title: { default: "MarosimGo Admin", template: "%s · MarosimGo" },
  description: "MarosimGo Super Admin boshqaruv paneli",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  colorScheme: "light dark",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f6f7f9" },
    { media: "(prefers-color-scheme: dark)", color: "#090d12" },
  ],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="uz" className={jakarta.variable} suppressHydrationWarning>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
