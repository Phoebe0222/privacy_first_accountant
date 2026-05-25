"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const links = [
  { href: "/", label: "Dashboard", icon: "📊" },
  { href: "/transactions", label: "Transactions", icon: "💳" },
  { href: "/import", label: "Import", icon: "📥" },
  { href: "/chat", label: "Chat", icon: "💬" },
  { href: "/rules", label: "Rules", icon: "🏷️" },
];

export default function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="w-56 min-h-screen bg-gray-900 text-white flex flex-col py-8 px-4 gap-2 shrink-0">
      <div className="mb-8 px-2">
        <h1 className="text-lg font-bold tracking-tight">Private Accountant</h1>
        <p className="text-xs text-gray-400 mt-1">100% local</p>
      </div>
      {links.map(({ href, label, icon }) => {
        const active = pathname === href;
        return (
          <Link
            key={href}
            href={href}
            className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${
              active ? "bg-blue-600 text-white" : "text-gray-300 hover:bg-gray-800"
            }`}
          >
            <span>{icon}</span>
            {label}
          </Link>
        );
      })}
    </aside>
  );
}
