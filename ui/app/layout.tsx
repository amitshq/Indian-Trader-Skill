import "./globals.css";
import Nav from "./Banner";

export const metadata = { title: "India Trader (practice)" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Nav />
        {children}
        <footer>
          Personal research tool. Not investment advice. Prices and data come from unofficial sources and can be delayed, stale or wrong:
          each screen shows how old its data is.
        </footer>
      </body>
    </html>
  );
}
