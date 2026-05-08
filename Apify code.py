async function pageFunction(context) {
    const $ = context.jQuery;
    const url = context.request.url;


    let jobDescription = '';
    let company = '';
    let jobTitle = '';


    // ---------------------------
    // SEEK
    // ---------------------------
    if (url.includes('seek.com')) {
        jobDescription = $('[data-automation="jobAdDetails"]').text();
        jobTitle = $('[data-automation="job-detail-title"]').text();
        company = $('[data-automation="advertiser-name"]').text();
    }


    // ---------------------------
    // INDEED
    // ---------------------------
    else if (url.includes('indeed.com')) {
        jobDescription = $('#jobDescriptionText').text();
        jobTitle = $('h1').first().text();
        company = $('[data-testid="inlineHeader-companyName"]').text();
    }


    // ---------------------------
    // LINKEDIN
    // ---------------------------
    else if (url.includes('linkedin.com')) {


        // Try primary selector
        jobDescription = $('.show-more-less-html__markup').text();


        // Backup selector
        if (!jobDescription || jobDescription.length < 200) {
            jobDescription = $('.jobs-description__content').text();
        }


        jobTitle = $('h1').first().text();
        company = $('.topcard__org-name-link').text() || $('.topcard__flavor').text();
    }


    // ---------------------------
    // FALLBACK (ANY SITE)
    // ---------------------------
    if (!jobDescription || jobDescription.length < 200) {
        jobDescription = $('p')
            .map((i, el) => $(el).text())
            .get()
            .join(' ');
    }


    // ---------------------------
    // CLEAN TEXT
    // ---------------------------
    jobDescription = jobDescription
        .replace(/\n/g, ' ')
        .replace(/\s+/g, ' ')
        .trim();


    jobTitle = jobTitle.trim();
    company = company.trim();


    context.log.info(`Scraped: ${url}`);


    return {
        url,
        jobTitle,
        company,
        jobDescription
    };
}




