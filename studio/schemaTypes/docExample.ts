import {defineField, defineType} from 'sanity'

/** A worked example copied from a platform page, never invented. */
export const docExample = defineType({
  name: 'docExample',
  title: 'Documented example',
  type: 'object',
  fields: [
    defineField({name: 'input', title: 'Input, as printed on the page', type: 'string'}),
    defineField({name: 'normalized', title: 'Normalized value, as printed on the page', type: 'string'}),
    defineField({
      name: 'sha256',
      title: 'Published SHA-256',
      type: 'string',
      description: 'Only when the page prints the digest.',
      validation: (rule) => rule.regex(/^[0-9a-f]{64}$/),
    }),
    defineField({name: 'region', title: 'Region the example assumes', type: 'string'}),
    defineField({
      name: 'diverges',
      title: 'The code deliberately does not reproduce this example',
      type: 'boolean',
      initialValue: false,
    }),
  ],
  preview: {
    select: {input: 'input', normalized: 'normalized', diverges: 'diverges'},
    prepare: ({input, normalized, diverges}) => ({
      title: `${input} → ${normalized}`,
      subtitle: diverges ? 'declared divergence' : 'reproduced by the code',
    }),
  },
})
