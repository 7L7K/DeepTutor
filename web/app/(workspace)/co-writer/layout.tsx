import { AdminOnlyGate } from "@/components/auth/AdminOnlyGate";

export default function CoWriterLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return <AdminOnlyGate>{children}</AdminOnlyGate>;
}
