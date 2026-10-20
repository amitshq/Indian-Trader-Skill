import Banner from "./Banner";

export const metadata = { title: "India Trader (paper)" };

const links: [string, string][] = [["/", "Dashboard"], ["/screener", "Screener"], ["/plan", "Plan"], ["/tax", "Tax"], ["/market", "Market"]];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body style={{ fontFamily: "system-ui, sans-serif", margin: 0, background: "#0f1115", color: "#e6e6e6" }}>
        <nav style={{ display: "flex", gap: 16, padding: "12px 24px", borderBottom: "1px solid #232733" }}>
          {links.map(([href, label]) => (
            <a key={href} href={href} style={{ color: "#8ab4f8", textDecoration: "none" }}>{label}</a>
          ))}
          <Banner />
        </nav>
        {children}
        <p style={{ textAlign: "center", opacity: 0.5, fontSize: 12, padding: 16 }}>
          Personal research tool. Not investment advice. Data from unofficial sources can be delayed or wrong.
        </p>
      </body>
    </html>
  );
}
