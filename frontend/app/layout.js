import "./globals.css";
import Nav from "@/components/Nav";

export const metadata = {
  title: "CT-MIF Monitor",
  description: "Multi-view Isolation-Forest anomaly detection with a 4-agent reasoning pipeline",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        <Nav />
        <main className="main">{children}</main>
      </body>
    </html>
  );
}
