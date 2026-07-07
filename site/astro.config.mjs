// @ts-check
import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';

// Project site served at https://berkayturanci.github.io/mac-sysdash/
export default defineConfig({
  site: 'https://berkayturanci.github.io',
  base: '/mac-sysdash',
  trailingSlash: 'ignore',
  integrations: [sitemap()],
});
