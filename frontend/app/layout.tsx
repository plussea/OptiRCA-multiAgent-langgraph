import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "OptiRCAgent Console",
  description: "光网络智能诊断系统运维操作台",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN">
      <body className="min-h-screen bg-background antialiased">
        {children}
      </body>
    </html>
  );
}
