/**
 * @typedef {import('../../frontend/node_modules/botasaurus-controls/dist/index').Controls} Controls
 */

/**
 * @param {Controls} controls
 */
function getInput(controls) {
    controls
        // Render a list of website inputs
        .listOfTexts('websites', {
            isRequired: true,
            label: 'Websites',
            placeholder: 'vercel.com',
            defaultValue: ["vercel.com"],
            helpText: 'Domains or URLs of the websites to extract contact details from',
        })
}
