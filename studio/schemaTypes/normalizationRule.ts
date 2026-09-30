import {defineArrayMember, defineField, defineType} from 'sanity'

/**
 * What the conversion-preflight code does for one platform and one field,
 * next to the documentation it was written against. Published from
 * preflight/rules.py by `python -m preflight.sanity_sync --apply`; edit the
 * Python module, not these documents, or the next sync reports drift.
 */
export const normalizationRule = defineType({
  name: 'normalizationRule',
  title: 'Normalization rule',
  type: 'document',
  readOnly: true,
  fields: [
    defineField({
      name: 'platform',
      type: 'string',
      options: {list: ['google', 'meta'], layout: 'radio'},
      validation: (rule) => rule.required(),
    }),
    defineField({
      name: 'field',
      type: 'string',
      options: {
        list: ['email', 'phone', 'first_name', 'last_name', 'city', 'state', 'postal_code', 'country'],
      },
      validation: (rule) => rule.required(),
    }),
    defineField({name: 'param', title: "Platform's parameter name", type: 'string'}),
    defineField({name: 'hashed', title: 'Sent as a SHA-256 digest', type: 'boolean'}),
    defineField({name: 'implemented', type: 'boolean'}),
    defineField({name: 'implementation', title: 'What the code does', type: 'text', rows: 4}),
    defineField({
      name: 'docQuote',
      title: "The platform's words when the code was written",
      type: 'text',
      rows: 4,
    }),
    defineField({
      name: 'source',
      type: 'object',
      fields: [
        defineField({name: 'url', type: 'url'}),
        defineField({name: 'note', title: 'Page version and retrieval date', type: 'string'}),
      ],
    }),
    defineField({
      name: 'kbEntry',
      title: 'Knowledge base entry that should agree today',
      type: 'string',
    }),
    defineField({
      name: 'docExamples',
      title: 'Worked examples from the page',
      type: 'array',
      of: [defineArrayMember({type: 'docExample'})],
    }),
    defineField({
      name: 'divergences',
      title: 'Differences the code makes on purpose',
      type: 'array',
      of: [defineArrayMember({type: 'string'})],
    }),
  ],
  preview: {
    select: {platform: 'platform', field: 'field', param: 'param', implemented: 'implemented'},
    prepare: ({platform, field, param, implemented}) => ({
      title: `${platform} / ${field}`,
      subtitle: implemented ? param : `${param} (not implemented)`,
    }),
  },
})
