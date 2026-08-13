import { AdminOnlyGate } from "@/components/auth/AdminOnlyGate";

export default function BookLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return <AdminOnlyGate>{children}</AdminOnlyGate>;
}
