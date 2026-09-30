import {defineArrayMember, defineField, defineType} from 'sanity'

/** The whole rule table as one document: every rule, plus what applies to all of them. */
export const implementationProfile = defineType({
  name: 'implementationProfile',
  title: 'Implementation profile',
  type: 'document',
  readOnly: true,
  fields: [
    defineField({name: 'name', type: 'string'}),
    defineField({name: 'upstream', title: 'Where the normaliser comes from', type: 'string'}),
    defineField({
      name: 'globalDivergences',
      title: 'Differences that apply to every rule',
      type: 'array',
      of: [defineArrayMember({type: 'string'})],
    }),
    defineField({
      name: 'rules',
      type: 'array',
      of: [defineArrayMember({type: 'reference', to: [{type: 'normalizationRule'}]})],
    }),
  ],
})
