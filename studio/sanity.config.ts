import {defineConfig} from 'sanity'
import {structureTool} from 'sanity/structure'

import {schemaTypes} from './schemaTypes'

export default defineConfig({
  name: 'default',
  title: 'conversion-preflight',
  projectId: 'h3njchfh',
  dataset: 'production',
  plugins: [structureTool()],
  schema: {types: schemaTypes},
})
