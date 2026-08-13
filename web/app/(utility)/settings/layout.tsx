import SettingsMain from "@/components/settings/SettingsMain";
import { SettingsProvider } from "@/components/settings/SettingsContext";
import { SettingsTourOverlay } from "@/components/settings/SettingsTourOverlay";
import { AdminOnlyGate } from "@/components/auth/AdminOnlyGate";

export default function SettingsLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <AdminOnlyGate>
      <SettingsProvider>
        <SettingsMain>{children}</SettingsMain>
        {/* Mounted once at the layout level so the cross-route guided tour
            survives navigation between the hub and its sub-pages. */}
        <SettingsTourOverlay />
      </SettingsProvider>
    </AdminOnlyGate>
  );
}
