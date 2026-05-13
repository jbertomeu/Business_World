**********************************************************************************************
*
* Code adapted from CEO-restatement20.do (only retains compensation part)
*
* Assembles dataset of CEO firm-years 2000-2016
*
* PREREQUISITES: The following do files must be run before running this file
* prep1: prepares csv files into stata format
* 
* firm level are in millions, CEO level are in thousands
**********************************************************************************************

**********************************************************************************************
* PART I: Prepare Execucomp annual main file
**********************************************************************************************

* read in ANNCOMP csv file
import delimited csv_files/ANNCOMP.csv, clear
sort co_per_rol year
by co_per_rol: gen shrown_excl_opts_l=shrown_excl_opts[_n-1]
by co_per_rol: gen stock_unvest_num_l=stock_unvest_num[_n-1]
by co_per_rol: gen eip_unearn_num_l=eip_unearn_num[_n-1]
keep if ceoann=="CEO"

sort gvkey year
drop term_pymt ceoann cfoann option_awards_fv option_awards_blk_value option_awards_rpt_value
save dta_files/compfile1, replace

* merge compustat
import delimited csv_files/COMPUSTAT_ANNUAL.csv, clear
do do_files/fix_compustat.do
drop if missing(prcc_f)
save dta_files/COMPUSTATCRSP_ANNUAL_new, replace

	** import into main database
	use dta_files/compfile1, replace
	merge n:1 gvkey year using dta_files/COMPUSTATCRSP_ANNUAL_new, keep(3) nogenerate
	keep if !missing(at) & !missing(ni)
	
* compute CEO variables

	** compute tenure
	do do_files/format_date becameceo
	sort co_per_rol pends
	gen tenure=max(0,(pends-becameceo)/365)
	drop became* left* joined*
	
	** compute turnover dates
	sort gvkey pends
	by gvkey: gen turnover=1 if co_per_rol!=co_per_rol[_n+1]
	by gvkey: replace turnover=. if missing(co_per_rol[_n+1])
	by gvkey: replace turnover=0 if co_per_rol==co_per_rol[_n+1]
	label variable turnover "new CEO in next fiscal year"
	
	** fix variables
	gen csh=cshfd
	replace csh=cshpri if missing(csh)
	replace lt=lt*at
	replace lt_l=lt_l*at_l
	gen equity=at-lt
	gen equity_l=at_l-lt_l
	replace ni=ni*at
	gen mcap=prcc_f*csh
	sort gvkey pends

* calculate return and winsorize
gen optret=(prcc_f+dvpsp_f-prcc_f_l)/prcc_f_l*100
winsor2 optret, cuts(0 99) replace
merge m:1 gvkey year using dta_files/WRDS_COMPUSTATCRSP, keep(1 3) nogenerate keepusing(rdq permno)
merge m:1 permno rdq using dta_files/MOMENTSCRSP, keep(1 3) keepusing(YoYret) nogenerate
replace optret=YoYret*100 if missing(optret)
winsor2 optret, cuts(0 99) replace
replace prcc_f_l=(prcc_f+dvpsp_f)/(1+optret/100) if missing(prcc_f_l)
drop if missing(optret)	
	
* compute non-option pay

	** average price	
	gen avgprice=(prcc_f+prcc_f_l)/2
	
	** fix missing to zero
	**A will assume restricted shares are NOT included in shrown_excl_opts
	replace rstkgrnt=0 if missing(rstkgrnt)
	replace opt_exer_val=0 if missing(opt_exer_val)
	replace shrown_excl_opts=0 if missing(shrown_excl_opts)
	replace shrown_excl_opts_l=0 if missing(shrown_excl_opts_l)
	replace stock_unvest_num=0 if missing(stock_unvest_num)
	replace eip_unearn_num=0 if missing(eip_unearn_num)
	replace shrs_vest_val=0 if missing(shrs_vest_val)
	
	** compute total pay (chg. in wealth, except options - later)
	
		*** non-equity pay
		egen tpay=rowtotal(total_curr othcomp ltip noneq_incent)
		replace tpay=max(0,tpay)
		
		*** shares owned
		replace tpay=tpay+(shrown_excl_opts+shrown_excl_opts_l)/2*avgprice*optret/100
	
		*** restricted shares + EIP
		*** A: do not accumulate dividend
		egen rshares=rowtotal(stock_unvest_num eip_unearn_num)
		egen rshares_l=rowtotal(stock_unvest_num_l eip_unearn_num_l)
		replace tpay=tpay+rshares*prcc_f-rshares_l*prcc_f_l+shrs_vest_val
	

save dta_files/compfile1, replace

	
**********************************************************************************************
* PART III: Prepare option file
**********************************************************************************************

* outstanding grant data
import delimited csv_files\PORTFOLIOS_EXECUCOMP.csv, clear

	** clean up
	rename prccf prcc_f
	drop execrank pceo pcfo title reason joined_co becameceo leftco leftofc
	label variable co_per_rol "Executive-Company identifier"
	rename opts_unex_exer options_vested
	label variable options_vested "Nb. options held that are vested, th."
	egen options_unvested=rowtotal(opts_unex_unexer opts_unex_unearn)
	drop opts_unex_unexer opts_unex_unearn
	label variable options_unvested "Nb. options held, unvested (unearn or unexercizable), th."
	label variable expric "Exercise price"
	label variable prcc_f "Closing stock price, fiscal year end"
	label variable year "Fiscal year"
	gsort co_per_rol year
	label variable cusip "8-digit CUSIP"
	do do_files/format_date.do exdate
	label variable exdate "Exercise date"

	** merge compustat data
	merge m:1 gvkey year using dta_files/COMPUSTATCRSP_ANNUAL_new, keep(3) keepusing(optvol optrfr prcc_f prcc_f_l optdr yield dvpsp_f pends) nogenerate
	merge m:1 gvkey year using dta_files/compfile1, keep(3) keepusing(optret) nogenerate
	
	
	** get eip and restricted from other database: show up as missing options
	replace options_vested=0 if missing(options_vested) 
	replace options_unvested=0 if missing(options_unvested) 
	drop if options_vested==0 & options_unvested==0 	

	** fix missing information in data
	
		*** typing errors
		***N JB: manually checked proxy filings (DEF14A), 10 decimals misplaced
		replace exdate=. if pends>exdate
		replace options_vested=max(0,options_vested)
		replace options_unvested=max(0,options_vested)

		*** fix missing exercise price or exercise date
		sort co_per_rol outawdnum year
		by co_per_rol outawdnum: replace expric=expric[_n-1] if missing(expric) & !missing(expric[_n-1])
		by co_per_rol outawdnum: replace exdate=exdate[_n-1] if missing(exdate) & !missing(exdate[_n-1])
		gsort co_per_rol outawdnum -year
		by co_per_rol outawdnum: replace expric=expric[_n-1] if missing(expric) & !missing(expric[_n-1])
		by co_per_rol outawdnum: replace exdate=exdate[_n-1] if missing(exdate) & !missing(exdate[_n-1])
		replace expric=0 if missing(expric)
		egen a1=max(exdate)
		replace exdate=a1 if missing(exdate)
		replace exdate=pends if pends>exdate	
		drop a1
		
		*** clean-up
		drop shrs_unvest_num shrs_unvest_val eip_shrs_unvest_num eip_shrs_unvest_val
		drop outawdnum
		gen fromgrants=1
		label variable fromgrants "Obs. comes from oustanding grants dataset"

		*** label variables
		drop page
		label variable gvkey "Compustat GVKEY"
		label variable coname "Company name"
		label variable exec_fullname "Full name of executive"
		label variable spcode "SP code: SP for SP500, MD for SP Midcap, SM for SP SmallCap, EX for not on major SP index"
		label variable exchange "Stock Exchange: NYS (NYSE), ASE (American), NAS (Nasdaq)"
		save temp/temp_options, replace

* Obtain required data to value options
use temp/temp_options, replace
drop coname cusip exchange spcode naics sic

	** fix missing
	replace optdr=yield*100 if missing(optdr)
	sort gvkey year
	by gvkey: replace optrfr=optrfr[_n-1] if missing(optrfr) & !missing(optrfr[_n-1])
	by gvkey: replace optvol=optvol[_n-1] if missing(optvol) & !missing(optvol[_n-1])
	by gvkey: replace optdr=optdr[_n-1] if missing(optdr) & !missing(optdr[_n-1])
	gsort gvkey -year
	by gvkey: replace optrfr=optrfr[_n-1] if missing(optrfr) & !missing(optrfr[_n-1])
	by gvkey: replace optvol=optvol[_n-1] if missing(optvol) & !missing(optvol[_n-1])
	by gvkey: replace optdr=optdr[_n-1] if missing(optdr) & !missing(optdr[_n-1])
	bys year: egen medrfr=median(optrfr)
	bys year: egen medvol=median(optvol)
	replace optrfr=medrfr if missing(optrfr)
	replace optvol=medvol if missing(optvol)
	drop medrfr medvol
	replace optdr=0 if missing(optdr)
	winsor2 optvol, replace cuts(1 99)
	winsor2 optrfr, replace cuts(1 99)
	save temp/temp_options, replace


* calculate BS values
use temp/temp_options, replace

	** Compute maturity
	gen timeleft=(exdate-pends)/365
	label variable timeleft "Time left on the option, in years"

	** calculate value of options from Black-Scholes
	**A assumes BS (time value lost from early exercise ~ small) and strike is adjusted for dividends
	replace optrfr=optrfr/100
	replace optvol=optvol/100
	replace optret=optret/100	
	do do_files/bs2

	** sum over portfolios
	collapse (sum) wealth_opts* (firstnm) year (firstnm) gvkey, by(co_per_rol pends)

* lagged wealth definition
sort co_per_rol pends
by co_per_rol: gen wealth_opts_l=wealth_opts[_n-1]

* keep only if CEO in main database
merge m:1 co_per_rol year using dta_files/ANNCOMP.dta, nogenerate keep(3) keepusing(becameceo)

* fix missing	
sort gvkey pends
by gvkey: replace wealth_opts_l=0 if missing(wealth_opts_l) & !missing(co_per_rol[_n-1])
save temp/temp_options, replace

* merge to main dataset and process option pay
use dta_files/compfile1, replace
merge m:1 co_per_rol year using temp/temp_options, keep(3) nogenerate keepusing(wealth_opts*)
replace opt_exer_val=0 if missing(opt_exer_val)
replace opt_exer_val=0 if missing(opt_exer_val)
replace wealth_opts=0 if missing(wealth_opts_l)
replace wealth_opts_l=0 if missing(wealth_opts_l)

replace tpay=tpay+wealth_opts-wealth_opts_l+opt_exer_val
label variable tpay "total pay"

save dta_files/compfile1, replace

use dta_files/compfile1, replace
keep gvkey co_per_rol pends exec_fullname year at ni lt mkvalt at_l lt_l ni_l tenure equity equity_l tpay optret mcap
save dta_files/compfile1_lite, replace

**********************************************************************************************
* PART IV: Extra Code for Gayle and Miller NP Model
**********************************************************************************************

use dta_files/compfile1_lite, replace

* do some more normalization (tpay rescaled in percent of mcap)
drop if missing(mcap)
replace tpay=0.001*tpay/(mcap/(1+optret/100))
gen ni_chg=ni-ni_l
keep tpay ni_chg optret
winsor2 tpay ni_chg optret, replace cuts(5 95)


* Set Risk-aversion
** Brenner 2013 Management Science. Table 5 mean CEO RRA
scalar r_RA=1.92 
** recalibrate to CARA at same Arrow-Pratt at mean tpay
sum tpay, mean
scalar r=r_RA*r(mean)


gen a= exp(-r*tpay)
gen b=exp(r*tpay)
gen bx=exp(r*tpay)*optret
egen maxw=max(tpay)
gen g=1/r*exp(r*maxw)
collapse a b g bx optret tpay

scalar mu=g-b/r
scalar wl=-1/r*log((r*a*g-1)/(r*g-b))
scalar c=1/r*log(1/a*(r*a*g-1)/(r*g-b))
scalar lambda= a*g*(r*g-b)/(r*a*g-1)-g+b/r
scalar bound=1/r*(bx-wl*b)-(mu+lambda)*c*(optret-wl)+optret-tpay

display wl
display c
display bound
