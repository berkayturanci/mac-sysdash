// @ts-check
import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';

// Project site served at https://berkayturanci.github.io/mac-sysdash/
export default defineConfig({
  site: 'https://berkayturanci.github.io',
  base: '/mac-sysdash',
  trailingSlash: 'ignore',
  // keep the canonical trailing-slash URL only — avoids the duplicate
  // /mac-sysdash + /mac-sysdash/ pair the plugin emits under a base path
  integrations: [sitemap({ filter: (page) => page.endsWith('/') })],
});
