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
        // Crawl depth per website
        .select('mode', {
            label: 'Crawl Mode',
            defaultValue: 'deep',
            options: [
                { value: 'homepage', label: 'Homepage only' },
                { value: 'key_pages', label: 'Key pages' },
                { value: 'deep', label: 'Deep' },
            ],
            helpText: 'Deep crawls up to 20 pages and finds the most emails. Key pages is faster but may miss them.',
        })
}
