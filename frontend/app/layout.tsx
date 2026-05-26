import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import Sidebar from "@/components/Sidebar";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Private Accountant",
  description: "Your local business accountant",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className={`${inter.className} bg-gray-50 flex`}>
        <Sidebar />
        <main className="flex-1 min-w-0 p-8 overflow-auto min-h-screen">{children}</main>
      </body>
    </html>
  );
}
