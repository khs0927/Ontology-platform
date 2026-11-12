import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Sion Console",
  description: "Sion Ontology Platform 계정, 구독, API 접근",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
