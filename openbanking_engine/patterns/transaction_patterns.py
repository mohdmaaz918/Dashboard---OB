"""
Transaction categorization patterns for HCSTC Loan Scoring.
Patterns for UK consumer lending based on PLAID format transaction data.
"""

# Income Categories (Credits - negative amounts)
INCOME_PATTERNS = {
    "salary": {
        "keywords": [
            # Core payroll terms
            "SALARY", "WAGES", "PAYROLL", "PAYSLIP", "NET SALARY", "GROSS PAY",
            "MONTHLY SALARY", "WEEKLY WAGES", "PAY RUN", "PAYRUN", "PAYE",
            "NET PAY", "WAGE", "EMPLOYER", "EMPLOYERS",
            
            # Payment method identifiers -- ONLY with salary context (standalone removed to avoid false positives)
            "BANK GIRO CREDIT",
            
            # Contract/employment terms
            "CHEQUERS CONTRACT", "CONTRACT PAY", "EMPLOYMENT PAYMENT",
            "STAFF PAYMENT", "EMPLOYEE PAYMENT",
            
            # Payroll providers
            "ADP", "PAYFIT", "SAGE PAYROLL", "XERO PAYRUN", "WORKDAY",
            "BARCLAYS PAYMENTS", "HSBC PAYROLL", "PAYCIRCLE",
            
            # Common employer suffixes (to catch "ABC LIMITED SALARY" patterns)
            # These will be used in regex patterns
        ],
        "regex_patterns": [
            # Core salary terms
            r"(?i)\b(salary|payroll|payslip|net\s*salary|gross\s*pay)\b",
            r"(?i)\b(monthly|weekly|fortnightly)\s*(salary|wages|pay)\b",
            
            # Payment methods + salary context
            r"(?i)\b(bacs|bgc|fps|fp-?)\s*(credit|payment)?\s*(salary|payroll|wages)\b",
            r"(?i)\b(salary|payroll|wages)\b.*\b(bacs|bgc|fps|fp-?)\b",
            
            # Bank giro credit (common UK salary method)
            r"(?i)\bbank\s*giro\s*credit\b",
            r"(?i)\bbgc\b",
            
            # Faster Payments with context
            r"(?i)\bfaster\s*payment\b.*\b(salary|payroll|wages|employment)\b",
            r"(?i)\bfp-?\b.*\b(salary|payroll|wages|pay)\b",
            
            # Pay run variations
            r"(?i)\bpay\s*run\b|\bpayrun\b",
            r"(?i)\bpaye\b",
            
            # Employment context
            r"(?i)\bemployment\b.*\b(payment|pay|salary|wages)\b",
            r"(?i)\b(payment|pay|salary|wages)\b.*\bemployment\b",
            
            # Payroll providers
            r"(?i)\badp\b.*\b(payroll|salary|wages|payment)\b",
            r"(?i)\bpayfit\b",
            r"(?i)\bsage\b.*\b(payroll|salary|wages)\b",
            r"(?i)\bxero\b.*\b(payrun|payroll|salary)\b",
            r"(?i)\bworkday\b.*\b(payroll|salary|wages)\b",
            
            # Company suffix patterns -- ONLY when salary/payroll context is also present
            # Bare "XYZ LTD" without payroll keywords is handled by transfer promotion in the engine
            r"(?i)\b(LTD|LIMITED|PLC|LLP|CORP|CORPORATION|INC)\b.*\b(salary|wages?|payroll|pay\s*run|payrun|paye)\b",
            r"(?i)\b(salary|wages?|payroll|pay\s*run|payrun|paye)\b.*\b(LTD|LIMITED|PLC|LLP|CORP|CORPORATION|INC)\b",
        ],
        "weight": 1.0,
        "is_stable": True,
        "description": "Salary & Wages"
    },

    "benefits": {
        "keywords": [
            "UNIVERSAL CREDIT", "DWP", "CHILD BENEFIT",
            "PIP", "DLA", "ESA", "JSA", "PENSION CREDIT",
            "HOUSING BENEFIT", "TAX CREDIT",
            "WORKING TAX CREDIT", "CHILD TAX CREDIT",
            "CARERS ALLOWANCE", "ATTENDANCE ALLOWANCE",
            "MATERNITY ALLOWANCE", "BEREAVEMENT BENEFIT",
            "SOCIAL SECURITY", "STATE BENEFIT",
            # Additional benefit variants (additive)
            "HMRC REFUND", "TAX REFUND", "HMRC TAX REFUND"
        ],
        "regex_patterns": [
            r"(?i)universal\s*credit",
            r"(?i)\b(dwp)\b.*\b(uc|esa|jsa|pip|dla)\b",
            r"(?i)child\s*benefit",
            r"(?i)\b(pip|dla|esa|jsa)\b",
            r"(?i)pension\s*credit",
            r"(?i)housing\s*benefit",
            r"(?i)(working|child)\s*tax\s*credit",
            r"(?i)carers?\s*allowance",
            r"(?i)attendance\s*allowance",
            r"(?i)maternity\s*allowance",
            r"(?i)(state|government|social)\s*(benefit|payment)",
            # Additional tax refund patterns (additive)
            r"(?i)\bhmrc\b.*\b(refund|tax\s*refund)\b",
            r"(?i)\btax\s*refund\b",
        ],
        "weight": 1.0,
        "is_stable": True,
        "description": "Benefits & Government Payments"
    },

    "pension": {
        "keywords": [
            "STATE PENSION", "ANNUITY", "PENSION PAYMENT", "PENSION CREDIT",
            "PENSION DRAWDOWN", "OCCUPATIONAL PENSION", "WORKS PENSION",
            "RETIREMENT INCOME",
            # Additional pension providers (additive)
            "NEST PENSION", "AVIVA PENSION", "LEGAL AND GENERAL PENSION",
            "SCOTTISH WIDOWS PENSION", "STANDARD LIFE PENSION", "PRUDENTIAL PENSION",
            "ROYAL LONDON PENSION", "AEGON PENSION"
        ],
        "regex_patterns": [
            r"(?i)\bstate\s*pension\b",
            r"(?i)\bannuity\b.*\b(payment|credit)\b|\b(payment|credit)\b.*\bannuity\b",
            r"(?i)\bpension\b.*\b(payment|credit|income)\b|\b(payment|credit|income)\b.*\bpension\b",
            r"(?i)\b(retirement)\s*(income|payment|credit)\b",
            r"(?i)\b(pension|annuity)\s*drawdown\b",
            r"(?i)\b(occupational|works)\s*pension\b",
            # Additional pension provider patterns (additive)
            r"(?i)\bnest\b.*\bpension\b",
            r"(?i)\baviva\b.*\bpension\b",
            r"(?i)\blegal\s*and\s*general\b.*\bpension\b",
            r"(?i)\bscottish\s*widows\b.*\bpension\b",
            r"(?i)\bstandard\s*life\b.*\bpension\b",
            r"(?i)\bprudential\b.*\bpension\b",
            r"(?i)\broyal\s*london\b.*\bpension\b",
            r"(?i)\baegon\b.*\bpension\b",
        ],
        "weight": 1.0,
        "is_stable": True,
        "description": "Pension Income"
    },

    "gig_economy": {
        "keywords": [
            "UBER", "DELIVEROO", "JUST EAT", "BOLT", "LYFT",
            "FIVERR", "UPWORK", "TASKRABBIT", "FREELANCER",
            "AMAZON FLEX", "ETSY", "EBAY", "VINTED", "DEPOP",
            # Additional gig platforms (additive)
            "UBER EATS", "EVRI", "DPD", "YODEL", "ROYAL MAIL",
            "SHOPIFY PAYMENTS", "STRIPE PAYOUT", "PAYPAL PAYOUT"
        ],
        "regex_patterns": [
            # Gig payout language -- requires gig platform context (standalone removed to avoid
            # matching "LOAN DISBURSEMENT", "INSURANCE SETTLEMENT", etc.)
            r"(?i)\b(payout|settlement|disbursement|earnings)\b.*\b(uber|deliveroo|just\s*eat|bolt|lyft|fiverr|upwork|etsy|ebay|vinted|depop|amazon\s*flex|evri|dpd|shopify|stripe|paypal)\b",
            r"(?i)\b(uber|deliveroo|just\s*eat|bolt|lyft|fiverr|upwork|etsy|ebay|vinted|depop|amazon\s*flex|evri|dpd|shopify|stripe|paypal)\b.*\b(payout|settlement|disbursement|earnings)\b",
            r"(?i)\b(driver\s*pay|weekly\s*pay|instant\s*pay)\b",

            # Uber payouts (including Uber Eats)
            r"(?i)\buber\b.*\b(payout|earnings|bv|payments|driver|eats)\b",
            r"(?i)\buber\s*eats\b.*\b(payout|earnings|payment)\b",

            # Deliveroo / Just Eat payouts
            r"(?i)\bdeliveroo\b.*\b(payout|earnings|settlement|payment)\b",
            r"(?i)\bjust\s*eat\b.*\b(payout|earnings|settlement|payment)\b",
            # Bolt payouts (tightened)
            r"(?i)\bbolt\b.*\b(payout|earnings|driver|settlement|payment)\b",

            # Lyft payouts
            r"(?i)\blyft\b.*\b(payout|earnings|settlement|payment)\b",

            # Fiverr / Upwork payouts
            r"(?i)\bfiverr\b.*\b(payout|withdrawal|payment|transfer)\b",
            r"(?i)\bupwork\b.*\b(payout|payment|transfer)\b",

            # Marketplace payouts (tightened)
            r"(?i)\bebay\b.*\b(payout|disbursement|managed\s*payments|settlement)\b",
            r"(?i)\betsy\b.*\b(payout|deposit|settlement|payment)\b",
            r"(?i)\bvinted\b.*\b(payout|transfer|payment)\b",
            r"(?i)\bdepop\b.*\b(payout|transfer|payment)\b",
            # Amazon Flex (tightened to avoid Amazon shopping refunds)
            r"(?i)\bamazon\b.*\b(flex|logistics)\b.*\b(payout|earnings|payment|settlement)\b",
            
            # Additional delivery/courier platforms (additive)
            r"(?i)\bevri\b.*\b(payout|earnings|payment)\b",
            r"(?i)\bdpd\b.*\b(payout|earnings|payment|driver)\b",
            r"(?i)\byodel\b.*\b(payout|earnings|payment|driver)\b",
            r"(?i)\broyal\s*mail\b.*\b(payout|earnings|payment)\b",
            
            # Payment processor payouts (additive)
            r"(?i)\bshopify\b.*\b(payout|payments|disbursement)\b",
            r"(?i)\bstripe\b.*\b(payout|transfer)\b",
            r"(?i)\bpaypal\b.*\b(payout|disbursement)\b",
        ],
        "weight": 1.0,
        "is_stable": False,
        "description": "Gig Economy Income"
    },

    "loans": {
        "keywords": [
            "LOAN DISBURSEMENT", "LOAN PAYOUT", "LOAN ADVANCE",
            "LOAN REFUND", "LOAN REVERSAL",
            "PERSONAL LOAN", "UNSECURED LOAN", "GUARANTOR LOAN",
            "ZOPA", "LENDABLE"
        ],
        "regex_patterns": [
            # Explicit loan language
            r"(?i)\b(personal|unsecured|guarantor)\s*loan\b",
            r"(?i)\bloan\b.*\b(disbursement|payout|advance|drawdown|top\s*up)\b",
            r"(?i)\b(disbursement|payout|advance|drawdown|top\s*up)\b.*\bloan\b",

            # Loan refund / reversal language
            r"(?i)\bloan\b.*\b(refund|reversal)\b|\b(refund|reversal)\b.*\bloan\b",

            # Known non-HCSTC lenders
            r"(?i)\bzopa\b",
            r"(?i)\blendable\b",
        ],
        "weight": 0.0,
        "is_stable": False,
        "description": "Loan Disbursements/Refunds (Not Income)"
    },

    "interest": {
        "keywords": [
            "INTEREST", "GROSS INTEREST", "INTEREST PAID", "INTEREST CREDIT",
            "BANK INTEREST", "SAVINGS INTEREST"
        ],
        "regex_patterns": [
            r"(?i)\binterest\b.*\b(paid|credit|payment|earned)\b",
            r"(?i)\bgross\s*int(erest)?\b",
            r"(?i)\bbank\s*interest\b",
            r"(?i)\bsavings\s*interest\b",
        ],
        "weight": 1.0,
        "is_stable": True,
        "description": "Interest Income"
    },
    
    "refund": {
        "keywords": [
            "REFUND", "REFUNDED", "RETURN", "RETURNED",
            "CREDIT REVERSAL", "CHARGEBACK", "REVERSAL", "MERCHANT DISPUTE"
        ],
        "regex_patterns": [
            r"(?i)\brefund(ed)?\b",
            r"(?i)\b(credit\s*)?reversal\b",
            r"(?i)\bcharge\s*back\b|\bchargeback\b",
            r"(?i)\b(dispute|merchant)\b.*\b(refund|reversal|credit)\b",
        ],
        "weight": 1.0,
        "is_stable": False,
        "description": "Refunds / Chargebacks"
    },
}

TRANSFER_PATTERNS = {
    "keywords": [
        "OWN ACCOUNT", "INTERNAL TRANSFER", "INTERNAL TFR", "BETWEEN ACCOUNTS",
        "SELF TRANSFER", "ACCOUNT TRANSFER", "TRANSFER BETWEEN",
        "FROM SAVINGS", "TO SAVINGS", "FROM CURRENT", "TO CURRENT",
        # Additional neobank and internal transfer keywords (additive)
        "REVOLUT", "MONZO", "STARLING", "CHASE", "WISE",
        "PAYPAL TOPUP", "SAVER", "ISA", "POT", "VAULT",
        "ROUND UP", "MOVE MONEY", "INTERNAL MOVE"
    ],
    "regex_patterns": [
        r"(?i)\bown\s*account\b",
        r"(?i)\bbetween\s*accounts\b",
        r"(?i)\bself\s*transfer\b",
        r"(?i)\binternal\s*(transfer|tfr|xfer|move)\b",
        r"(?i)\baccount\s*transfer\b|\btransfer\s*between\b",
        r"(?i)\b(move(d)?|transfer(red)?)\b.*\b(from|to)\b.*\b(savings|current)\b",
        r"(?i)\b(from|to)\b\s*(savings|current)\b.*\b(transfer|tfr|xfer|moved?)\b",
        r"(?i)\b(faster\s*payment|fps|fp)\b.*\b(transfer|tfr|xfer)\b",

        # WARNING: see note below about standing order / so
        r"(?i)\bstanding\s*order\b",
        
        # Additional neobank patterns (additive)
        r"(?i)\brevolut\b.*\b(transfer|top\s*up|pot|vault|move)\b",
        r"(?i)\bmonzo\b.*\b(transfer|pot|move)\b",
        r"(?i)\bstarling\b.*\b(transfer|space|move)\b",
        r"(?i)\bchase\b.*\b(transfer|move|internal)\b",
        r"(?i)\bwise\b.*\b(transfer|move)\b",
        r"(?i)\bpaypal\b.*\btop\s*up\b",
        
        # Internal movement patterns (additive)
        r"(?i)\b(saver|pot|vault|space)\b.*\b(transfer|move|moved)\b",
        r"(?i)\bround\s*up\b",
        r"(?i)\bmove\s*money\b",
        r"(?i)\binternal\s*move\b",
    ],
    "weight": 0.0,
    "is_stable": False,
    "description": "Internal / Own-Account Transfers (Not Income)"
    }


DEBT_PATTERNS = {
    "hcstc_payday": {
    "keywords": [
        "LENDING STREAM", "DRAFTY", "MR LENDER", "MONEYBOAT",
        "CREDITSPRING", "CASHFLOAT", "QUIDMARKET", "LOANS 2 GO",
        "LOANS2GO", "CASHASAP", "POLAR CREDIT", "118 118 MONEY",
        "THE MONEY PLATFORM", "FAST LOAN UK", "SALAD MONEY",
        "FAIR FINANCE", "MYJAR", "PEACHY",
        "AMIGO", "SUNNY", "WONGA"
    ],
    "regex_patterns": [
        r"(?i)\blending\s*stream\b",
        r"(?i)\bdrafty\b",
        r"(?i)\bmr\s*lender\b",
        r"(?i)\bmoneyboat\b",
        r"(?i)\bcreditspring\b",
        r"(?i)\bcashfloat\b",
        r"(?i)\bquidmarket\b",
        r"(?i)\bloans?\s*2\s*go\b",
        r"(?i)\bcashasap\b",
        r"(?i)\bpolar\s*credit\b",
        r"(?i)\b118\s*118\s*money\b",
        r"(?i)\bthe\s*money\s*platform\b",
        r"(?i)\bfast\s*loan\s*uk\b",
        r"(?i)\bsalad\s*money\b",
        r"(?i)\bfair\s*finance\b",
        r"(?i)\bmyjar\b",
        r"(?i)\bpeachy\b",
        r"(?i)\bamigo\b",
        r"(?i)\bsunny\b",
        r"(?i)\bwonga\b",
        # Conduit tightened
        r"(?i)\bconduit\b.*\b(loan|lending|finance|credit)\b",
    ],
    "risk_level": "very_high",
    "description": "HCSTC / Payday Lenders"
},

    "other_loans": {
    # Personal, guarantor & sub-prime loans (use specific lenders + high-signal phrases)
    "keywords": [
        "ZOPA", "NOVUNA", "FINIO LOANS", "EVLO", "EVERYDAY LOANS",
        "BAMBOO", "LIVELEND", "LENDABLE",
        "PERSONAL LOAN PAYMENT", "LOAN REPAYMENT",
        "CAR FINANCE", "AUTO FINANCE", "VEHICLE FINANCE",
        "HIRE PURCHASE", "HP AGREEMENT"
    ],
    "regex_patterns": [
        # High-signal loan repayment language (requires repayment/payment)
        r"(?i)\bloan\b.*\b(repayment|payment)\b|\b(repayment|payment)\b.*\bloan\b",
        r"(?i)\bpersonal\s*loan\b.*\b(payment|repayment)\b",
        r"(?i)\bcredit\s*agreement\b.*\b(payment|repayment)\b",

        # Vehicle / HP finance (use full phrase, not 'HP' alone)
        r"(?i)\b(hire\s*purchase|hp\s*agreement)\b",
        r"(?i)\b(car|auto|vehicle)\s*finance\b",

        # Known lenders
        r"(?i)\bzopa\b",
        r"(?i)\bnovuna\b",
        r"(?i)\bfinio\s*loans?\b",
        r"(?i)\bevlo\b",
        r"(?i)\beveryday\s*loans?\b",
        r"(?i)\bbamboo\b",
        r"(?i)\blivelend\b",
        r"(?i)\blendable\b",
    ],
    "risk_level": "medium",
    "description": "Other Loans"
},

    "credit_cards": {
    # Credit cards (specialist + mainstream card brands). Avoid generic bank names.
    "keywords": [
        "VANQUIS", "AQUA", "CAPITAL ONE", "MARBLES", "ZABLE",
        "TYMIT", "118 118 MONEY CARD", "FLUID", "CHROME",
        "BARCLAYCARD", "AMEX", "AMERICAN EXPRESS", "MBNA", "NEWDAY",
        "VIRGIN MONEY CREDIT CARD", "SAINSBURYS BANK CREDIT CARD",
        "TESCO BANK CREDIT CARD", "M&S BANK CREDIT CARD"
    ],
    "regex_patterns": [
        r"(?i)\bvanquis\b",
        r"(?i)\baqua\b",
        r"(?i)\bcapital\s*one\b",
        r"(?i)\bmarbles\b",
        r"(?i)\bzable\b",
        r"(?i)\btymit\b",
        r"(?i)\b118\s*118\s*money\s*card\b",
        r"(?i)\bfluid\b.*\b(card|credit|repayment)\b",
        r"(?i)\bchrome\b.*\b(card|credit|repayment)\b",
        r"(?i)\bbarclaycard\b",
        r"(?i)\bamex\b|\bamerican\s*express\b",
        r"(?i)\bmbna\b",
        r"(?i)\bnewday\b",

        # Generic repayment language (high-signal)
        r"(?i)\bcredit\s*card\b.*\b(payment|repayment|minimum|balance|statement)\b",
        r"(?i)\bcard\s+repayment\b",
        r"(?i)\bminimum\s*payment\b",
        r"(?i)\bstatement\s*balance\b",

        # Bank-branded cards only when 'credit card' is explicit
        r"(?i)\b(virgin\s*money|sainsbury'?s\s*bank|tesco\s*bank|m\s*&\s*s\s*bank)\b.*\b(credit\s*card|card\s*payment)\b",
        r"(?i)\bm\s*&\s*s\s*bank\b.*\bpayment\b",
    ],
    "risk_level": "low",
    "description": "Credit Cards"
},

    "bnpl": {
    # Buy Now Pay Later (UK providers)
    "keywords": [
        "KLARNA", "CLEARPAY", "ZILCH", "MONZO FLEX",
        "PAYPAL PAY IN 3", "PAYPAL PAY IN 4",
        "RIVERTY", "PAYL8R", "LAYBUY", "SCALAPAY", "HUMM"
    ],
    "regex_patterns": [
        r"(?i)\bklarna\b",
        r"(?i)\bclearpay\b",
        r"(?i)\bzilch\b",
        r"(?i)\bmonzo\s*flex\b",
        r"(?i)\bpaypal\b.*\bpay\s*in\s*(3|4)\b",
        r"(?i)\briverty\b",
        r"(?i)\bpayl8r\b",
        r"(?i)\blaybuy\b",
        r"(?i)\bscalapay\b",
        r"(?i)\bhumm\b",
    ],
    "risk_level": "high",
    "description": "Buy Now Pay Later"
},

    "catalogue": {
    "keywords": [
        "LITTLEWOODS", "JD WILLIAMS", "FREEMANS", "GRATTAN",
        "SIMPLY BE", "JACAMO", "AMBROSE WILSON", "FASHION WORLD",
        "CATALOGUE PAYMENT", "CATALOG PAYMENT",
        "VERY.COM", "VERY PAY", "VERY ACCOUNT"
    ],
    "regex_patterns": [
        # Very (tightened)
        r"(?i)\bvery(\.com)?\b.*\b(account|payment|pay|credit|shopdirect|catalogue|catalog)\b",
        r"(?i)\bshopdirect\b.*\b(very|littlewoods)\b",

        # Littlewoods / Shop Direct ecosystem
        r"(?i)\blittlewoods\b",
        r"(?i)\bjd\s*williams\b",
        r"(?i)\bfreemans\b",
        r"(?i)\bgrattan\b",
        r"(?i)\bsimply\s*be\b",
        r"(?i)\bjacamo\b",
        r"(?i)\bambrose\s*wilson\b",
        r"(?i)\bfashion\s*world\b",

        # Studio (tightened: must have context)
        r"(?i)\bstudio\b.*\b(catalogue|catalog|account|payment|credit)\b",

        # M&S catalogue (ok, but keep it catalogue-gated)
        r"(?i)\b(marks\s*(&|and)?\s*spencer|m\s*&\s*s)\b.*\b(catalogue|catalog)\b",

        # Generic catalogue phrases (good)
        r"(?i)\b(catalogue|catalog)\b.*\b(payment|account|credit)\b",
    ],
    "risk_level": "medium",
    "description": "Catalogue Credit"
},
}

# Essential Living Costs
ESSENTIAL_PATTERNS = {
    "rent": {
        "keywords": [
            "LANDLORD", "LETTING AGENT", "LETTING AGENCY", "TENANCY",
            "HOUSING ASSOCIATION", "COUNCIL RENT", "PROPERTY RENT", "RENT PAYMENT"
        ],
        "regex_patterns": [
            r"(?i)\bhousing\s*association\b",
            r"(?i)\bcouncil\s*rent\b",
            r"(?i)\btenanc(y|ies)\b",
            r"(?i)\blandlord\b",
            r"(?i)\bletting\s*(agent|agency)\b",
            r"(?i)\brent\b.*\b(property|tenancy|landlord|letting|flat|house|ha|council)\b",
            r"(?i)\b(property|tenancy|landlord|letting|flat|house|ha|council)\b.*\brent\b",
        ],
        "is_housing": True,
        "description": "Rent"
    },
    "mortgage": {
    "keywords": [
        "MORTGAGE", "MORTGAGE PAYMENT", "HOME LOAN", "MTG"
    ],
    "regex_patterns": [
        r"(?i)\bmortgage\b",
        r"(?i)\bhome\s*loan\b",
        r"(?i)\bmtg\b",
        r"(?i)\bmortgage\b.*\b(payment|repayment|dd|direct\s*debit)\b",
        r"(?i)\b(payment|repayment|dd|direct\s*debit)\b.*\bmortgage\b",

        # lender names only when mortgage context exists
        r"(?i)\b(nationwide|halifax|santander|barclays|hsbc|lloyds|natwest|tsb|virgin\s*money|skipton|leeds|yorkshire|coventry)\b.*\bmortgage\b",
        r"(?i)\bmortgage\b.*\b(nationwide|halifax|santander|barclays|hsbc|lloyds|natwest|tsb|virgin\s*money|skipton|leeds|yorkshire|coventry)\b",
    ],
    "is_housing": True,
    "description": "Mortgage"
},

    "council_tax": {
    "keywords": [
        "COUNCIL TAX"
    ],
    "regex_patterns": [
        # Primary: explicit council tax
        r"(?i)\bcouncil\s*tax\b",
        r"(?i)\bctax\b",

        # Council names only when council tax context is present
        r"(?i)\b(borough|city|district|county)\s*council\b.*\bcouncil\s*tax\b",
        r"(?i)\bcouncil\s*tax\b.*\b(borough|city|district|county)\s*council\b",
        r"(?i)\blocal\s*authority\b.*\bcouncil\s*tax\b",
        r"(?i)\bcouncil\s*tax\b.*\blocal\s*authority\b",
    ],
    "description": "Council Tax"
},

    "utilities": {
    "keywords": [
        "BRITISH GAS", "EDF ENERGY", "E.ON", "EON ENERGY", "SSE",
        "OCTOPUS", "OCTOPUS ENERGY", "BULB", "SCOTTISH POWER",
        "THAMES WATER", "SEVERN TRENT", "ANGLIAN WATER",
        "UNITED UTILITIES", "SOUTHERN WATER", "YORKSHIRE WATER",
        "WATER BILL", "GAS BILL", "ELECTRICITY BILL", "ENERGY BILL"
    ],
    "regex_patterns": [
        # Suppliers
        r"(?i)\bbritish\s*gas\b",
        r"(?i)\bedf(\s*energy)?\b",
        r"(?i)\be\.?on\b(\s*energy)?",
        r"(?i)\bsse\b",
        r"(?i)\boctopus(\s*energy)?\b",
        r"(?i)\bbulb\b",
        r"(?i)\bscottish\s*power\b",

        # Water companies
        r"(?i)\bthames\s*water\b",
        r"(?i)\bsevern\s*trent\b",
        r"(?i)\banglian\s*water\b",
        r"(?i)\b(united\s*utilities|southern\s*water|yorkshire\s*water)\b",

        # Generic utilities language (must include bill/payment/DD)
        r"(?i)\b(electricity|gas|water|energy)\b.*\b(bill|payment|dd|direct\s*debit)\b",
        r"(?i)\b(bill|payment|dd|direct\s*debit)\b.*\b(electricity|gas|water|energy)\b",
    ],
    "description": "Utilities"
},

    "communications": {
    "keywords": [
        "VIRGIN MEDIA", "VODAFONE", "PLUSNET", "TALKTALK",
        "BT BROADBAND", "SKY BROADBAND", "SKY TV", "NOW BROADBAND",
        "TV LICENCE", "EE LIMITED", "O2 UK", "THREE MOBILE"
    ],
    "regex_patterns": [
        # Broadband / telecoms providers (require service/bill context where token is short)
        r"(?i)\bbt\b.*\b(broadband|phone|line\s*rental|bill|payment)\b",
        r"(?i)\bsky\b.*\b(tv|broadband|bill|payment)\b",
        r"(?i)\bvirgin\s*media\b",
        r"(?i)\bvodafone\b",
        r"(?i)\bplusnet\b",
        r"(?i)\btalktalk\b",

        # Mobile networks (tightened)
        r"(?i)\bee\b.*\b(bill|payment|mobile|contract)\b",
        r"(?i)\bo2\b.*\b(bill|payment|mobile|uk|contract)\b",
        r"(?i)\bthree\b.*\b(mobile|3\s*mobile|uk|bill|payment|contract)\b",

        # TV licence
        r"(?i)\btv\s*lic(e|en)(s|c)e\b",

        # Generic comms language
        r"(?i)\b(mobile|broadband|internet|phone)\b.*\b(bill|payment|contract)\b",
        r"(?i)\b(bill|payment|contract)\b.*\b(mobile|broadband|internet|phone)\b",
    ],
    "description": "Communications (Telecoms/Broadband/TV Licence)"
},

    "insurance": {
    "keywords": [
        # Insurers
        "AVIVA", "DIRECT LINE", "ADMIRAL", "CHURCHILL",
        "HASTINGS", "ESURE", "SWINTON", "MORE THAN",
        # Breakdown providers (often bundled with insurance but still ok here)
        "RAC", "AA",
        # Generic insurance phrases (high-signal)
        "INSURANCE PREMIUM", "CAR INSURANCE", "HOME INSURANCE", "LIFE INSURANCE"
    ],
    "regex_patterns": [
        # High-signal generic insurance language
        r"(?i)\binsurance\b.*\b(premium|payment|policy|cover)\b",
        r"(?i)\b(premium|policy|cover)\b.*\binsurance\b",
        r"(?i)\b(car|home|life|contents|motor)\s*insurance\b",

        # Insurers (boundaries where helpful)
        r"(?i)\baviva\b",
        r"(?i)\bdirect\s*line\b",
        r"(?i)\badmiral\b",
        r"(?i)\bchurchill\b",
        r"(?i)\bhastings\b",
        r"(?i)\besure\b",
        r"(?i)\bswinton\b",
        r"(?i)\bmore\s*than\b.*\b(insurance|premium|policy|cover)\b",

        # Breakdown (gate AA hard; RAC is OK with \b)
        r"(?i)\brac\b.*\b(breakdown|cover|membership|policy|payment)\b",
        r"(?i)\baa\b.*\b(insurance|breakdown|cover|membership|policy|payment)\b",

        # Comparison sites ONLY when insurance context is present
        r"(?i)\bconfused\.?com\b.*\b(insurance|premium|policy|cover)\b",
        r"(?i)\bcompare\s*the\s*market\b.*\b(insurance|premium|policy|cover)\b",
    ],
    "description": "Insurance"
},

    "transport": {
    "keywords": [
        # Fuel brands (use full brand tokens rather than short abbreviations)
        "SHELL", "ESSO", "TEXACO",
        # Public transport / rail
        "TFL", "OYSTER", "NATIONAL RAIL", "TRAINLINE", "RAILCARD",
        # Charges
        "CONGESTION CHARGE", "ULEZ", "BUS PASS"
    ],
    "regex_patterns": [
        # Fuel stations (brand-based is safest)
        r"(?i)\bshell\b",
        r"(?i)\besso\b",
        r"(?i)\btexaco\b",

        # If you really want BP, do it only in regex (NOT keywords)
        r"(?i)\bbp\b.*\b(fuel|petrol|diesel|service\s*station)\b",

        # Public transport
        r"(?i)\btfl\b",
        r"(?i)\boyster\b",
        r"(?i)\bnational\s*rail\b",
        r"(?i)\btrainline\b",
        r"(?i)\brailcard\b",

        # Parking (require payment/charge context)
        r"(?i)\bparking\b.*\b(charge|payment|fee|ncp|ringgo|paybyphone)\b",
        r"(?i)\b(ncp|ringgo|paybyphone)\b.*\b(parking|park)\b",

        # Congestion / ULEZ
        r"(?i)\bcongestion\s*charge\b",
        r"(?i)\bulez\b",
    ],
    "description": "Transport"
},

    "groceries": {
    "keywords": [
        "TESCO", "SAINSBURY", "ASDA", "MORRISONS", "ALDI", "LIDL",
        "WAITROSE", "M&S FOOD", "M&S SIMPLY FOOD",
        "ICELAND", "FARMFOODS", "OCADO", "AMAZON FRESH",
        "CO-OP FOOD", "COOP FOOD"
    ],
    "regex_patterns": [
        # Tesco (avoid mobile/bank)
        r"(?i)\btesco\b(?!.*\b(mobile|bank|personal\s*finance)\b)",
        # Sainsbury (avoid bank)
        r"(?i)\bsainsbury'?s?\b(?!.*\bbank\b)",
        # Asda etc.
        r"(?i)\basda\b",
        r"(?i)\bmorrisons\b",
        r"(?i)\baldi\b",
        r"(?i)\blidl\b",
        r"(?i)\bwaitrose\b",

        # M&S FOOD only (not general retail/bank)
        r"(?i)\b(m\s*&\s*s|marks\s*(and|&)?\s*spencer)\b.*\b(food|simply\s*food)\b",

        # Co-op food (avoid Co-operative Bank)
        r"(?i)\bco-?op\b.*\b(food|store|stores|supermarket)\b",
        r"(?i)\bco-?op\b(?!.*\bbank\b)",

        # Others
        r"(?i)\biceland\b",
        r"(?i)\bfarmfoods\b",
        r"(?i)\bocado\b",
        r"(?i)\bamazon\b.*\bfresh\b",
    ],
    "description": "Groceries"
},

    "childcare": {
    "keywords": [
        "CHILDCARE", "CHILDMINDER", "CRECHE", "PRESCHOOL",
        "AFTER SCHOOL", "BREAKFAST CLUB", "HOLIDAY CLUB", "NANNY",
        "DAYCARE", "WRAPAROUND CARE"
    ],
    "regex_patterns": [
        r"(?i)\bchild\s*care\b|\bchildcare\b",
        r"(?i)\bchildminder\b",
        r"(?i)\bcr[eè]che\b|\bcreche\b",
        r"(?i)\bpre-?school\b|\bpreschool\b",
        r"(?i)\b(after\s*school|breakfast\s*club|holiday\s*club)\b",
        r"(?i)\bnanny\b",
        r"(?i)\bwrap\s*around\s*care\b|\bwraparound\s*care\b",

        # Nursery ONLY when childcare context is present (avoids plant nurseries)
        r"(?i)\bnursery\b.*\b(child|kids|children|school|fees|care)\b",
        r"(?i)\b(child|kids|children|school|fees|care)\b.*\bnursery\b",
    ],
    "description": "Childcare"
},
}

# Risk Indicator Categories
RISK_PATTERNS = {
    "gambling": {
        "keywords": [
            # Operators / brands (high-signal)
            "BET365", "BETFAIR", "WILLIAM HILL", "LADBROKES", "CORAL",
            "PADDY POWER", "BETFRED", "POKERSTARS", "SKYBET", "UNIBET",
            "BWIN", "BETWAY", "TOMBOLA", "GROSVENOR", "NATIONAL LOTTERY",
            "DRAFTKINGS", "FANDUEL", "CASUMO"
        ],
        "regex_patterns": [
            # Major UK operators
            r"(?i)\bbet365\b",
            r"(?i)\bbetfair\b",
            r"(?i)\bwilliam\s*hill\b",
            r"(?i)\bladbrokes\b",
            r"(?i)\bcoral\b",
            r"(?i)\bpaddy\s*power\b",
            r"(?i)\bbetfred\b",
            r"(?i)\bpokerstars\b",
            r"(?i)\bskybet\b",
            r"(?i)\bunibet\b",
            r"(?i)\bbwin\b",
            r"(?i)\bbetway\b",
            r"(?i)\btombola\b",
            r"(?i)\bgrosvenor\b.*\b(casino|gaming)\b",
            r"(?i)\bnational\s*lottery\b|\blotto\b",
            # 888 brands – DO NOT match just “888”
            r"(?i)\b888\s*(casino|sport|sports|poker)\b",
            r"(?i)\b888casino\b|\b888poker\b|\b888sport\b",

            # Generic gambling terms ONLY when payment/top-up context exists
            r"(?i)\b(casino|betting|gambling|poker|bingo)\b.*\b(top\s*up|deposit|stake|wager|gaming|bookmaker|bookmakers|sportsbook)\b",
            r"(?i)\b(top\s*up|deposit|stake|wager)\b.*\b(casino|betting|gambling|poker|bingo)\b",
        ],
        "risk_level": "critical",
        "description": "Gambling"
    },

    "bank_charges": {
        "keywords": [
            "UNPAID ITEM CHARGE", "UNPAID TRANSACTION FEE",
            "RETURNED ITEM FEE", "RETURNED DD FEE", "RETURNED PAYMENT FEE",
            "UNPAID DD CHARGE", "UNPAID SO CHARGE",
            "BOUNCE FEE",
            "INSUFFICIENT FUNDS FEE", "NSF FEE",
            "OVERDRAFT FEE", "OVERDRAFT CHARGE",
            "PENALTY CHARGE", "UNPAID CHARGE", "RETURNED FEE", "ITEM FEE"
        ],
        "regex_patterns": [
            # Core: unpaid/returned/bounced + charge/fee
            r"(?i)\b(unpaid|returned|bounced|failed|dishono(u)?red)\b.*\b(charge|fee)\b",
            r"(?i)\b(charge|fee)\b.*\b(unpaid|returned|bounced|failed|dishono(u)?red)\b",

            # Insufficient funds / NSF
            r"(?i)\b(nsf|insufficient\s*funds)\b.*\b(charge|fee)\b",
            r"(?i)\b(charge|fee)\b.*\b(nsf|insufficient\s*funds)\b",

            # Overdraft charges
            r"(?i)\boverdraft\b.*\b(charge|fee)\b",
            r"(?i)\b(charge|fee)\b.*\boverdraft\b",

            # Item/transaction fees ONLY when penalty context exists
            r"(?i)\b(item|transaction)\b.*\b(charge|fee)\b.*\b(unpaid|returned|nsf|insufficient|overdraft)\b",
            r"(?i)\b(unpaid|returned|nsf|insufficient|overdraft)\b.*\b(item|transaction)\b.*\b(charge|fee)\b",
        ],
        "risk_level": "high",
        "description": "Bank charges for unpaid/returned items"
    },


    "failed_payments": {
        "keywords": [
            "UNPAID DIRECT DEBIT", "UNPAID DD", "DD UNPAID",
            "RETURNED DIRECT DEBIT", "RETURNED DD", "DD RETURNED",
            "BOUNCED PAYMENT", "BOUNCED DD", "BOUNCED DIRECT DEBIT",
            "PAYMENT RETURNED", "PAYMENT BOUNCED", "PAYMENT FAILED",
            "FAILED DIRECT DEBIT", "FAILED DD", "DD FAILED",
            "DISHONOURED DD", "DISHONOURED DIRECT DEBIT", "DISHONOURED PAYMENT",
            "INSUFFICIENT FUNDS DD",
            "DD RETURN", "DIRECT DEBIT RETURN", "RETURNED PAYMENT",

            # Common extra bank phrasing
            "UNPAID ITEM", "RETURNED ITEM", "REFER TO PAYER", "REPRESENTED DD"
        ],
        "regex_patterns": [
            # Core: unpaid/returned/bounced/failed/dishonoured + dd/payment
            r"(?i)\b(unpaid|returned|bounced|failed|dishono(u)?red)\b.*\b(direct\s*debit|dd|payment)\b",
            r"(?i)\b(direct\s*debit|dd|payment)\b.*\b(unpaid|returned|bounced|failed|dishono(u)?red)\b",

            # Insufficient funds
            r"(?i)\binsufficient\s*funds?\b.*\b(direct\s*debit|dd|payment)\b",
            r"(?i)\bno\s*funds\b.*\b(direct\s*debit|dd|payment)\b",

            # Returned item phrasing
            r"(?i)\b(unpaid|returned)\s*item\b",
            r"(?i)\brefer\s*to\s*payer\b",

            # Re-presented / represented direct debits
            r"(?i)\b(represented|re-?presented)\b.*\b(direct\s*debit|dd)\b",
        ],
        "risk_level": "critical",
        "description": "Failed payment events (DD/payment returned/failed)"
    },


   "debt_collection": {
        "keywords": [
            # High-signal DCAs / purchasers
            "LOWELL", "CABOT", "INTRUM", "ARROW GLOBAL", "LINK FINANCIAL",
            "MOORCROFT", "CAPQUEST", "MACKENZIE HALL",

            # Better-specific Hoist
            "HOIST FINANCE",

            # Generic phrases (kept but gated by regex below)
            "DEBT COLLECTION", "DEBT RECOVERY", "COLLECTIONS AGENCY"
        ],
        "regex_patterns": [
            # Explicit debt collection / recovery
            r"(?i)\bdebt\s*collect(ion|or)?\b",
            r"(?i)\bdebt\s*recovery\b",

            # “collections” ONLY when debt context exists
            r"(?i)\bcollections?\b.*\b(debt|recovery|agency|collector)\b",
            r"(?i)\b(debt|recovery|agency|collector)\b.*\bcollections?\b",

            # DCA token ONLY when debt context exists
            r"(?i)\bdca\b.*\b(debt|collect|recovery)\b",
            r"(?i)\b(debt|collect|recovery)\b.*\bdca\b",

            # Named firms
            r"(?i)\blowell\b",
            r"(?i)\bcabot\b",
            r"(?i)\bintrum\b",
            r"(?i)\barrow\s*global\b",
            r"(?i)\blink\s*financial\b",
            r"(?i)\bmoorcroft\b",
            r"(?i)\bcapquest\b",
            r"(?i)\bmackenzie\s*hall\b",

            # Hoist (tight)
            r"(?i)\bhoist\b.*\bfinance\b",

            # “credit solutions” only when debt context exists
            r"(?i)\bcredit\s*solutions\b.*\b(debt|collection|recovery)\b",
            r"(?i)\b(debt|collection|recovery)\b.*\bcredit\s*solutions\b",
        ],
        "risk_level": "severe",
        "description": "Debt Collection / Debt Purchasers"
    },

}

# Expense Categories (for categorizing specific expense types)
# Unpaid/overdraft/gambling share definitions with RISK_PATTERNS to avoid drift
EXPENSE_PATTERNS = {
    "unpaid": {
        "keywords": RISK_PATTERNS["bank_charges"]["keywords"],
        "regex_patterns": RISK_PATTERNS["bank_charges"]["regex_patterns"],
        "description": "Unpaid/Returned/NSF Fees"
    },

    "unauthorised_overdraft": {
        "keywords": [
            "OVERDRAFT FEE", "OVERDRAFT CHARGE",
            "UNARRANGED OVERDRAFT", "UNAUTHORISED OVERDRAFT",
            "OVERDRAFT INTEREST", "OVERDRAFT PENALTY"
        ],
        "regex_patterns": [
            r"(?i)\boverdraft\b.*\b(charge|fee|penalty|interest)\b",
            r"(?i)\b(charge|fee|penalty|interest)\b.*\boverdraft\b",
            r"(?i)\b(unauthori[sz]ed|unarranged|unauth)\b.*\boverdraft\b",
            r"(?i)\boverdraft\b.*\b(unauthori[sz]ed|unarranged|unauth)\b",
        ],
        "description": "Overdraft Fees"
    },

    "gambling": {
        "keywords": RISK_PATTERNS["gambling"]["keywords"],
        "regex_patterns": RISK_PATTERNS["gambling"]["regex_patterns"],
        "description": "Gambling"
    },
}

    # Positive Indicators
POSITIVE_PATTERNS = {
    "savings": {
        "keywords": [
            "SAVINGS", "ISA", "INVESTMENT",
            "MONEYBOX", "PLUM",
            "NUTMEG", "VANGUARD", "FIDELITY", "HARGREAVES", "AJ BELL",
            "PREMIUM BONDS", "NS&I"
        ],
        "regex_patterns": [
            r"(?i)\bsavings\b",
            r"(?i)\bisa\b",
            r"(?i)\binvest(ment|ing)\b",
            r"(?i)\bmoneybox\b",
            r"(?i)\bplum\b",
            r"(?i)\bnutmeg\b",
            r"(?i)\bvanguard\b",
            r"(?i)\bfidelity\b",
            r"(?i)\bhargreaves\b",
            r"(?i)\baj\s*bell\b",
            r"(?i)\bpremium\s*bonds?\b",
            r"(?i)\bns&?i\b",

            # CHIP app (tight match – avoids CHIPotle)
            r"(?i)\bchip\b\s*(financial|fin|savings|ltd|limited)?\b",
        ],
        "description": "Savings Activity"
    },
}

