"""Test content for the two brands, written only from what their own websites say.

Every claim below is taken from the brand's live site (source URLs are kept on
each draft's internal notes). Nothing here invents a project, offer, price,
testimonial or result. The drafts are created as drafts and sent for review;
none is approved or scheduled by the seeding.

``day`` / ``time`` form the proposed seven-day calendar, counted from the day
after seeding, in the workspace's timezone (Asia/Kolkata).
"""

NEOPOLIS_SITE = "https://www.neopolisinfra.com"
MORESPACE_SITE = "https://morespace.netlify.app"

SOCIAL_DRAFTS = {
    "neopolis": [
        {
            "key": "neopolis-landlord-share-explainer",
            "day": 1,
            "time": "10:30",
            "title": "What a landlord's share is",
            "caption": (
                "What is a landlord's share?\n\n"
                "When a landowner gives their plot to a developer under a joint-development agreement, "
                "the finished flats are split between them. The owner's portion — the landlord's share — "
                "sits in the same tower, with the same spec and amenities, but outside the launch "
                "marketing machine and the broker chain.\n\n"
                "Same tower, same spec — just a fairer number. Typically 8–14% under comparable resale.\n\n"
                "How the share works: https://www.neopolisinfra.com/#/the-share\n\n"
                "#LandlordShare #WestHyderabad #HyderabadRealEstate #NeopolisInfra"
            ),
            "x_caption": (
                "A landlord's share is the landowner's allocation in a joint development: same tower, same spec — "
                "typically 8–14% under comparable resale. How it works: https://www.neopolisinfra.com/#/the-share"
            ),
            "image": "https://www.neopolisinfra.com/assets/img/og-cover.jpg",
            "image_alt": "Neopolis Infra — landlord-share flats in West Hyderabad",
            "sources": [f"{NEOPOLIS_SITE}/", f"{NEOPOLIS_SITE}/#/the-share"],
        },
        {
            "key": "neopolis-title-first",
            "day": 3,
            "time": "18:30",
            "title": "Title-verified before you see it",
            "caption": (
                "Title first, always.\n\n"
                "Every landlord-share flat is title-verified before it reaches your shortlist. We check:\n"
                "• Clear, marketable title and a registered development agreement\n"
                "• Approved plans and the owner's specific flat allocation, in writing\n"
                "• No competing claims, and a clean path to registration in your name\n\n"
                "Your own advocate is welcome to review the same documents.\n\n"
                "WhatsApp or call +91 95336 86567 · Mon–Sun, 9 AM–9 PM\n\n"
                "#LandlordShare #HyderabadRealEstate #NeopolisInfra"
            ),
            "x_caption": (
                "Every landlord-share flat we show is title-verified first: clear title, registered development "
                "agreement, approved plans, the owner's allocation in writing. WhatsApp +91 95336 86567."
            ),
            "image": "https://neopolisinfra.com/assets/img/projects/aerial-skyline.webp",
            "image_alt": "Premium high-rise apartments in West Hyderabad",
            "sources": [f"{NEOPOLIS_SITE}/#/the-share", f"{NEOPOLIS_SITE}/#/about"],
        },
        {
            "key": "neopolis-documents-checklist",
            "day": 5,
            "time": "18:30",
            "title": "Documents checklist (blog)",
            "caption": (
                "Buying a flat in Hyderabad? Check the documents before you pay anything.\n\n"
                "Our checklist walks through the registered sale deed, the Encumbrance Certificate (EC), "
                "Dharani, TS-RERA, the approved plan and the occupancy certificate — with the red flags "
                "that should make you walk away.\n\n"
                "Read it: https://www.neopolisinfra.com/blog/property-documents-verification-checklist-hyderabad-2026\n\n"
                "#HyderabadRealEstate #HomeBuying #NeopolisInfra"
            ),
            "x_caption": (
                "Before you pay for a Hyderabad flat: sale deed, EC, Dharani, TS-RERA, approved plan, OC — and the "
                "red flags. Checklist: https://www.neopolisinfra.com/blog/property-documents-verification-checklist-hyderabad-2026"
            ),
            "image": (
                "https://www.neopolisinfra.com/blog/img/property-documents-verification-checklist-hyderabad-2026-hero.jpg"
            ),
            "image_alt": "Property documents verification checklist for buying a flat in Hyderabad",
            "sources": [f"{NEOPOLIS_SITE}/blog/property-documents-verification-checklist-hyderabad-2026"],
        },
        {
            "key": "neopolis-six-corridors",
            "day": 7,
            "time": "10:30",
            "title": "Six corridors, one direct line in",
            "caption": (
                "Six West Hyderabad corridors, one direct line in:\n\n"
                "Kokapet — financial-district edge\n"
                "Narsingi — ORR connectivity\n"
                "Neopolis — planned layout\n"
                "Manchirevula — lake views\n"
                "Tellapur — IT-corridor proximity\n"
                "Kollur — value entry\n\n"
                "Tell us the corridor and your budget. We'll come back with verified, direct-priced "
                "landlord shares — usually the same day.\n\n"
                "Projects: https://www.neopolisinfra.com/projects/\n\n"
                "#Kokapet #Narsingi #Tellapur #Kollur #WestHyderabad"
            ),
            "x_caption": (
                "Kokapet, Narsingi, Neopolis, Manchirevula, Tellapur, Kollur — tell us the corridor and budget, we "
                "reply with verified, direct-priced landlord shares. https://www.neopolisinfra.com/projects/"
            ),
            "image": "https://neopolisinfra.com/assets/img/projects/ssi-fortune-grande-neopolis.webp",
            "image_alt": "Landlord-share high-rise in Neopolis, Kokapet — West Hyderabad",
            "sources": [f"{NEOPOLIS_SITE}/", f"{NEOPOLIS_SITE}/projects/"],
        },
    ],
    "morespace": [
        {
            "key": "morespace-three-ways",
            "day": 1,
            "time": "18:30",
            "title": "Three ways we get you a better deal",
            "caption": (
                "Three ways More Space gets you a better deal in Hyderabad:\n\n"
                "Landlord Shares — early access to landlord-held units in under-construction and pre-launch phases.\n"
                "Investor Flats — resale of units acquired by early-stage investors.\n"
                "Builder Inventory — select premium units marketed directly with reputed developers.\n\n"
                "Tell us your budget, location and lifestyle — we'll shortlist the right options.\n"
                "WhatsApp +91 70751 68306\n\n"
                "#HyderabadRealEstate #LandlordShare #MoreSpace"
            ),
            "x_caption": (
                "Landlord shares, investor flats and builder inventory — three routes to a better deal on a "
                "Hyderabad home. Tell us your budget and location: WhatsApp +91 70751 68306."
            ),
            "image": (
                "https://assets.zyrosite.com/cdn-cgi/image/format=auto,w=900,h=680,fit=crop/AMq19Z68OEtq90DG/"
                "ragava-iris-6_cropped_page-0001-ALpPBMOQ9DhXK2bG.jpg"
            ),
            "image_alt": "Premium residential project in Hyderabad",
            "sources": [f"{MORESPACE_SITE}/"],
        },
        {
            "key": "morespace-soul-of-earth",
            "day": 2,
            "time": "11:00",
            "title": "Upcoming: Soul of Earth, Kukatpally",
            "caption": (
                "Upcoming launch: Soul of Earth, Kukatpally.\n\n"
                "25 acres, 11 towers and an 8-acre Central-Park-inspired courtyard — 3 & 4 BHK Vastu homes "
                "with 3 clubhouses.\n\n"
                "Get in before the formal launch: https://morespace.netlify.app/kukatpally.html\n"
                "WhatsApp +91 70751 68306\n\n"
                "#Kukatpally #HyderabadRealEstate #MoreSpace"
            ),
            "x_caption": (
                "Upcoming: Soul of Earth, Kukatpally — 25 acres, 11 towers, an 8-acre courtyard, 3 & 4 BHK homes. "
                "https://morespace.netlify.app/kukatpally.html"
            ),
            "image": (
                "https://assets.zyrosite.com/cdn-cgi/image/format=auto,w=760,h=560,fit=crop/AMq19Z68OEtq90DG/"
                "513083668_10043339375761994_2646727081486807655_n-mjEGQWXJBJcoBoXy.jpg"
            ),
            "image_alt": "Soul of Earth, Kukatpally — upcoming residential project",
            "sources": [f"{MORESPACE_SITE}/", f"{MORESPACE_SITE}/kukatpally.html"],
        },
        {
            "key": "morespace-how-we-work",
            "day": 4,
            "time": "11:00",
            "title": "How we work",
            "caption": (
                "At More Space, finding your home should be smooth, honest and enjoyable.\n\n"
                "Transparency first — clear, honest guidance at every step.\n"
                "Data-driven advice — recommendations backed by real market insight.\n"
                "Personal attention — from first visit to handover.\n\n"
                "Book a consultation: https://morespace.netlify.app/contact.html\n\n"
                "#HyderabadHomes #MoreSpace"
            ),
            "x_caption": (
                "Transparency first, data-driven advice, personal attention — from first visit to handover. "
                "Book a consultation: https://morespace.netlify.app/contact.html"
            ),
            "image": (
                "https://assets.zyrosite.com/cdn-cgi/image/format=auto,w=1600,h=900,fit=crop/AMq19Z68OEtq90DG/"
                "screenshot-2025-06-26-140123-YanJ6aqErrS1kv3K.png"
            ),
            "image_alt": "More Space — premium high-rise residences in Hyderabad",
            "sources": [f"{MORESPACE_SITE}/", f"{MORESPACE_SITE}/about.html"],
        },
        {
            "key": "morespace-rajendra-nagar-eoi",
            "day": 6,
            "time": "11:00",
            "title": "Rajendra Nagar: now accepting EOI",
            "caption": (
                "Rajendra Nagar (Gaganpahad) — now accepting EOI.\n\n"
                "Two prelaunch gated communities — 8-acre (724 units) and 13-acre (9 towers, G+33) — "
                "minutes from the PVNR Expressway.\n\n"
                "Details: https://morespace.netlify.app/rajendra-nagar.html\n"
                "WhatsApp +91 70751 68306\n\n"
                "#RajendraNagar #HyderabadRealEstate #MoreSpace"
            ),
            "x_caption": (
                "Rajendra Nagar (Gaganpahad), now accepting EOI: two prelaunch gated communities near the PVNR "
                "Expressway. https://morespace.netlify.app/rajendra-nagar.html"
            ),
            "image": (
                "https://assets.zyrosite.com/cdn-cgi/image/format=auto,w=760,h=560,fit=crop/AMq19Z68OEtq90DG/"
                "whatsapp-image-2025-05-09-at-12.30-AQEZ4MG0QvUWnzEg.jpg"
            ),
            "image_alt": "Rajendra Nagar prelaunch gated community",
            "sources": [f"{MORESPACE_SITE}/", f"{MORESPACE_SITE}/rajendra-nagar.html"],
        },
    ],
}

BLOG_DRAFTS = {
    "neopolis": {
        "key": "neopolis-blog-joint-development",
        "title": "Joint Development Agreements Explained: Where Landlord-Share Flats Come From",
        "slug": "joint-development-agreement-landlord-share-explained",
        "category": "Buyer Guide",
        "seo_title": "Joint Development & Landlord-Share Flats Explained",
        "meta_description": (
            "How a joint development creates the landowner's share of flats in West Hyderabad, why it can cost less "
            "than resale, and what to check before you buy."
        ),
        "excerpt": (
            "Most landlord-share flats start life in a joint development agreement. Here is how the landowner's "
            "allocation is created, why it often prices below resale, and the checks that matter before you buy."
        ),
        "image": "https://neopolisinfra.com/assets/img/projects/aerial-skyline.webp",
        "image_alt": "High-rise apartments in West Hyderabad built under joint development",
        "body": """\
Most buyers never hear the term **landlord's share** until they are deep in a deal. It describes the flats a landowner receives when they hand their plot to a developer under a **joint development agreement** — and it is the only thing Neopolis Infra deals in.

## How a joint development works

In a typical West Hyderabad project the landowner does not sell the plot outright. They contribute the land; the developer contributes the construction. When the tower is complete, the flats are divided between them in an agreed ratio — for example, 40% to the owner and 60% to the developer.

The developer markets its share the usual way: launches, sales teams, and a price that carries that overhead. The owner's share sits outside that machine.

## Why the owner's share can cost less

- **No marketing load.** The owner's flats do not fund advertising campaigns or sales commissions.
- **The owner often wants liquidity.** Many landowners prefer cash to flats, so they price to move.
- **Same building, same specification.** The flats are in the same tower, with the same amenities, as the developer's units.

In practice, a well-negotiated landlord share typically lands about 8–14% below comparable resale in the same project. The actual difference depends on the specific flat, floor and negotiation.

## Is it legally different after registration?

No. Once the sale deed is registered in your name, a landlord-share flat is legally identical to any other flat in the project — same ownership rights, same title, same access to amenities and the same freedom to resell. "Landlord share" describes how the flat was originally allocated, not a different class of ownership.

## What to check before you buy

Every share we show is checked before it reaches your shortlist:

1. Clear, marketable title and a **registered development agreement**.
2. **Approved plans** and the owner's specific flat allocation, in writing.
3. **No competing claims**, and a clean path to registration in your name.

Your own advocate is welcome to review the same documents. Stamp duty and registration charges in Telangana are set by the state and payable on top of the purchase price; confirm the current rates at the time of purchase.

## Talk to a real person

Tell us the corridor — Kokapet, Narsingi, Neopolis, Manchirevula, Tellapur or Kollur — and your budget. We reply with verified, direct-priced options, usually the same day: WhatsApp or call +91 95336 86567, Mon–Sun, 9 AM–9 PM.
""",
        "faq": [
            {
                "q": "What is a landlord's share in a joint development?",
                "a": "It is the set of finished flats a landowner receives in return for giving their land to a developer under a joint development agreement.",
            },
            {
                "q": "Is a landlord-share flat different after registration?",
                "a": "No. Once the sale deed is registered in your name it is legally identical to any other flat in the project.",
            },
        ],
        "sources": [f"{NEOPOLIS_SITE}/#/the-share", f"{NEOPOLIS_SITE}/"],
    },
    "morespace": {
        "key": "morespace-blog-three-routes",
        "title": "Landlord Shares, Investor Flats or Builder Inventory: Which Route Fits Your Hyderabad Home Search?",
        "slug": "landlord-shares-investor-flats-builder-inventory-hyderabad",
        "category": "Buyer Guide",
        "seo_title": "Landlord Shares, Investor Flats or Builder Inventory?",
        "meta_description": (
            "Three ways to buy a premium Hyderabad flat — landlord shares, investor flats and builder inventory — "
            "and how More Space helps you choose the right route."
        ),
        "excerpt": (
            "Landlord shares, investor flats and builder inventory are three different routes into the same "
            "premium projects. Here is how each works and who it suits."
        ),
        "image": (
            "https://assets.zyrosite.com/cdn-cgi/image/format=auto,w=1600,h=900,fit=crop/AMq19Z68OEtq90DG/"
            "screenshot-2025-06-26-140123-YanJ6aqErrS1kv3K.png"
        ),
        "image_alt": "Premium high-rise residences in Hyderabad",
        "body": """\
Buying into a premium high-rise in Hyderabad is not one transaction type. At More Space we work across three routes, so you can choose the one that fits your budget, timeline and goals.

## 1. Landlord shares

Early access to landlord-held units in under-construction and pre-launch phases. These are the flats a landowner receives from the developer, offered at competitive rates with room to negotiate.

**Suits:** buyers who are comfortable with an under-construction timeline and want an earlier entry point.

## 2. Investor flats

Resale of units acquired by early-stage investors. These can offer an attractive entry price and quicker deal execution than waiting for a new launch.

**Suits:** buyers who want a specific project or tower that has already launched.

## 3. Builder inventory

Select premium units marketed directly with reputed developers, with priority inventory and a streamlined purchase process.

**Suits:** buyers who want the full choice of units and a direct developer purchase.

## How we help

- **Transparency first** — clear, honest guidance at every step.
- **Data-driven advice** — recommendations backed by real market insight.
- **Personal attention** — from the first site visit to handover.

Tell us your budget, location and lifestyle, and we will shortlist the right options. WhatsApp +91 70751 68306, or book a consultation at morespace.netlify.app/contact.html.
""",
        "faq": [],
        "sources": [f"{MORESPACE_SITE}/", f"{MORESPACE_SITE}/about.html"],
    },
}
