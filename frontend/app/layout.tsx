import type { Metadata } from "next";
import "./globals.css";
import Sidebar from "@/components/Sidebar";

export const metadata: Metadata = {
  title: "Private Accountant",
  description: "Your local business accountant",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-gray-50 flex" style={{ fontFamily: "ui-sans-serif, system-ui, -apple-system, sans-serif" }}>
        <Sidebar />
        <main className="flex-1 min-w-0 p-8 overflow-auto min-h-screen">{children}</main>
      </body>
    </html>
  );
}
