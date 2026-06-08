"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

const TAX_PATHS = ["/bas", "/deductions", "/tax-settings"];

const links = [
  { href: "/", label: "Dashboard", icon: "📊" },
  { href: "/transactions", label: "Transactions", icon: "💳" },
  { href: "/receipts", label: "Receipts", icon: "🧾" },
  { href: "/reconciliation", label: "Reconcile", icon: "🔗" },
  { href: "/review", label: "Review", icon: "🔍" },
  { href: "/anomalies", label: "Anomalies", icon: "⚠️" },
  { href: "/import", label: "Import", icon: "📥" },
  { href: "/chat", label: "Chat", icon: "💬" },
];

const taxLinks = [
  { href: "/tax-settings", label: "Settings" },
  { href: "/bas", label: "BAS / GST" },
  { href: "/deductions", label: "Deductions" },
];

export default function Sidebar() {
  const pathname = usePathname();
  const onTaxPage = TAX_PATHS.includes(pathname);
  const [taxOpen, setTaxOpen] = useState(onTaxPage);

  return (
    <aside className="w-56 min-h-screen bg-gray-900 text-white flex flex-col py-8 px-4 gap-2 shrink-0">
      <div className="mb-8 px-2">
        <h1 className="text-lg font-bold tracking-tight">Private Accountant</h1>
        <p className="text-xs text-gray-400 mt-1">100% local</p>
      </div>

      {links.map(({ href, label, icon }) => (
        <Link
          key={href}
          href={href}
          className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${
            pathname === href ? "bg-blue-600 text-white" : "text-gray-300 hover:bg-gray-800"
          }`}
        >
          <span>{icon}</span>
          {label}
        </Link>
      ))}

      {/* Tax group */}
      <button
        onClick={() => setTaxOpen((o) => !o)}
        className={`flex items-center justify-between px-3 py-2 rounded-lg text-sm transition-colors w-full text-left ${
          onTaxPage ? "text-white" : "text-gray-300 hover:bg-gray-800"
        }`}
      >
        <span className="flex items-center gap-3">
          <span>🧮</span>
          Tax
        </span>
        <span className="text-gray-500 text-xs">{taxOpen ? "▲" : "▼"}</span>
      </button>

      {taxOpen && (
        <div className="ml-4 flex flex-col gap-1 border-l border-gray-700 pl-3">
          {taxLinks.map(({ href, label }) => (
            <Link
              key={href}
              href={href}
              className={`py-1.5 px-2 rounded-lg text-sm transition-colors ${
                pathname === href ? "bg-blue-600 text-white" : "text-gray-400 hover:text-white hover:bg-gray-800"
              }`}
            >
              {label}
            </Link>
          ))}
        </div>
      )}
    </aside>
  );
}
