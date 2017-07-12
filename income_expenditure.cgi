#!/usr/bin/perl

use strict;
use warnings;

use DBI;
use Fcntl qw/:flock SEEK_END/;

require "./conf.pl";

our($db,$db_user,$db_pwd,$log_d,$doc_root,$upload_dir);

my %session;
my %auth_params;

my $id;
my $logd_in = 0;
my $authd = 0;
my $accountant = 0;

my $con;
my ($key,$iv,$cipher) = (undef, undef,undef);

if ( exists $ENV{"HTTP_SESSION"} ) {

	my @session_data = split/&/,$ENV{"HTTP_SESSION"};
	my @tuple;

	for my $unprocd_tuple (@session_data) {
		#came to learn (as often happens, purely by accident)
		#doing a split/=/,x= will give a list with a size of 1
		#desirable here (where it's OK to ignore unset vars)
		#would be awful where even a blank var means something (e.g
		#logging in with a blank password)
		@tuple = split/\=/,$unprocd_tuple;

		if (@tuple == 2) {
			$tuple[0] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$tuple[1] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$session{$tuple[0]} = $tuple[1];		
		}
	}

	#logged in 
	if (exists $session{"id"}) {
		$logd_in++;
		$id = $session{"id"};
		#only bursar(user 2) can publish a fee structure 
		if ( $id eq "2" ) {

			$accountant++;
			if (exists $session{"sess_key"} ) {
				$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});

				use MIME::Base64 qw /decode_base64/;
				use Crypt::Rijndael;

				my $decoded = decode_base64($session{"sess_key"});
				my @decoded_bytes = unpack("C*", $decoded);

				my @sess_init_vec_bytes = splice(@decoded_bytes, 32);
				my @sess_key_bytes = @decoded_bytes;

				#read enc_keys_mem
				my $prep_stmt3 = $con->prepare("SELECT init_vec,aes_key FROM enc_keys_mem WHERE u_id=? LIMIT 1");

				if ( $prep_stmt3 ) {

					my $rc = $prep_stmt3->execute($id);

					if ( $rc ) {

						my ($mem_init_vec, $mem_aes_key) = (undef,undef);

						while (my @rslts = $prep_stmt3->fetchrow_array()) {
							$mem_init_vec = $rslts[0];
							$mem_aes_key = $rslts[1];
						}

						if ( defined $mem_init_vec ) {

							my @mem_init_vec_bytes = unpack("C*", $mem_init_vec);
							my @mem_aes_key_bytes = unpack("C*", $mem_aes_key);

							my ( @decrypted_init_vec, @decrypted_aes_key );

							for (my $i = 0; $i < @mem_init_vec_bytes; $i++) {
								$decrypted_init_vec[$i] = $mem_init_vec_bytes[$i] ^ $sess_init_vec_bytes[$i];
							}

							for (my $j = 0; $j < @mem_aes_key_bytes; $j++) {
								$decrypted_aes_key[$j] = $mem_aes_key_bytes[$j] ^ $sess_key_bytes[$j];
							}

							$key = pack("C*", @decrypted_aes_key);
							$iv = pack("C*", @decrypted_init_vec);

							$cipher = Crypt::Rijndael->new($key, Crypt::Rijndael::MODE_CBC());
							$cipher->set_iv($iv);

							$authd++;

						}
					}
					else {
						print STDERR "Couldn't execute SELECT FROM enc_keys_mem: ", $prep_stmt3->errstr, $/;
					}

				}
				else {
					print STDERR "Couldn't prepare SELECT FROM enc_keys_mem: ", $prep_stmt3->errstr, $/;
				}
			}
		}
	}
}

my $content = '';
my $feedback = '';
my $js = '';

my $header =
qq{
<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Accounts Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/">
	</iframe>
	<p><a href="/">Home</a> --&gt; <a href="/accounts/">Accounts</a> --&gt; <a href="/cgi-bin/income_expenditure.cgi">Create Income/Expenditure Statement</a>
	<hr> 
};

unless ($authd) {
	if ($logd_in) {
		my $err = qq!<p><span style="color: red">Sorry, you do not have the appropriate privileges to create a balance sheet.</span> Only the bursar is authorized to take this action.!;

		#key issues?
		if ( $accountant ) {

			$err = qq!<p><span style="color: red">Sorry, could not obtain the encryption keys needed to manage accounts.</span> Try <a href="/cgi-bin/logout.cgi">logging out</a> and then log in again. If this problem persists, contact support.!;

		}

		$content .=
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj::Accounts Management Information System::Create Income/Expenditure Statement</title>
</head>
<body>
$header

</body>
</html> 
*;
		print "Status: 200 OK\r\n";
		print "Content-Type: text/html; charset=UTF-8\r\n";

		my $len = length($content);
		print "Content-Length: $len\r\n";

		my @new_sess_array = ();

		for my $sess_key (keys %session) {
			push @new_sess_array, $sess_key."=".$session{$sess_key};        
		}
		my $new_sess = join ('&',@new_sess_array);

		print "X-Update-Session: $new_sess\r\n";

		print "\r\n";
		print $content;
		exit 0;
	}
	else {
		print "Status: 302 Moved Temporarily\r\n";
		print "Location: /login.html?cont=/cgi-bin/income_expenditure.cgi\r\n";
		print "Content-Type: text/html; charset=UTF-8\r\n";
       		my $res = 
qq!
<html lang="en">
<head>
<title>Spanj::Accounts Management Information System::Create Income/Expenditure Statement</title>
</head>
<body>
$header
You should have been redirected to <a href="/login.html?cont=/cgi-bin/income_expenditure.cgi">/login.html?cont=/cgi-bin/income_expenditure.cgi</a>. If you were not, <a href="login.html?cont=/cgi-bin/income_expenditure.cgi">Click Here</a> 
</body>
</html>!;

		my $content_len = length($res);	
		print "Content-Length: $content_len\r\n";
		print "\r\n";
		print $res;
		exit 0;
	}
}

my $post_mode = 0;
my $boundary = undef;
my $multi_part = 0;

if (exists $ENV{"REQUEST_METHOD"} and uc($ENV{"REQUEST_METHOD"}) eq "POST") {
	

	if (exists $ENV{"CONTENT_TYPE"}) {
		if ($ENV{"CONTENT_TYPE"} =~ m!multipart/form-data;\sboundary=(.+)!i) {
			$boundary = $1;
			$multi_part++;
		}
	}

	unless ($multi_part) {
		my $str = "";

		while (<STDIN>) {
        	       	$str .= $_;
	       	}

		my $space = " ";
		$str =~ s/\x2B/$space/ge;
		my @auth_req = split/&/,$str;

		for my $auth_req_line (@auth_req) {
			my $eqs = index($auth_req_line, "=");	
			if ($eqs > 0) {
				my ($k, $v) = (substr($auth_req_line, 0, $eqs), substr($auth_req_line, $eqs + 1));
				$k =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
				$v =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
				$auth_params{$k} = $v;
			}
		}
	}
	#processing data sent 
	$post_mode++;
}

PM: {
if ( $post_mode ) {

	#valid,non-automated request
	if ( not exists $auth_params{"confirm_code"} or not exists $session{"confirm_code"} or $auth_params{"confirm_code"} ne $session{"confirm_code"} ) {
		$feedback = qq!<span style="color: red">Invalid tokens sent.</span>!;
		$post_mode = 0;
		last PM;
	}

	unless ( exists $auth_params{"date"} ) {
		$feedback = qq!<span style="color: red">You did not specify the date.</span>!;
		$post_mode = 0;
		last PM;
	}

	my $show_sub_categories = 0;

	if ( exists $auth_params{"show_sub_categories"} and $auth_params{"show_sub_categories"} eq "1" ) {
		$show_sub_categories = 1;
	}

	use Time::Local;	
	my $stop_time;

	if ( $auth_params{"date"} =~ m!^([0-9]{1,2})/([0-9]{1,2})/([0-9]{2}(?:[0-9]{2})?)$! ) {

		my @today = localtime(time);
		my $current_yr = $today[5] + 1900;
		my @stop_date = ($1,$2 - 1,$3);

		if (length($stop_date[2]) == 2) {
			my $current_century = substr($current_yr, 0, 2);
			$stop_date[2] = $current_century . $stop_date[2];
		}

		unless ($stop_date[0] < 32 and $stop_date[1] < 13 and $stop_date[2] <= $current_yr) {
			$feedback = qq!<span style="color: red">You did not specify a valid start date.</span>!;
			$post_mode = 0;
			last PM;
		}

		$stop_time = timelocal(59,59,23,@stop_date);
	}
	else {
		$feedback = qq!<span style="color: red">You did not specify valid date.</span>!;
		$post_mode = 0;
		last PM;
	}

	use Digest::HMAC_SHA1 qw/hmac_sha1_hex/;	

	#read current budget
	my %voteheads = ();	
	my %child_lookup = ();
	my %votehead_hierarchy = ();

	${$votehead_hierarchy{"arrears"}}{"arrears"}++;
	$voteheads{"arrears"} = {"name" => "Arrears", "income" => 0};

	my $has_children = 0;

	my $prep_stmt2 = $con->prepare("SELECT votehead,votehead_parent,amount,hmac FROM budget");
	
	if ( $prep_stmt2 ) {

		my $rc = $prep_stmt2->execute();
		
		if ( $rc ) {

			while (my @rslts = $prep_stmt2->fetchrow_array()) {		

				my $decrypted_votehead = $cipher->decrypt( $rslts[0] );
				my $votehead = remove_padding($decrypted_votehead);
	
				my $decrypted_votehead_parent = $cipher->decrypt( $rslts[1] );
				my $votehead_parent = remove_padding($decrypted_votehead_parent);

				my $decrypted_amnt = $cipher->decrypt( $rslts[2] );	
				my $amnt = remove_padding($decrypted_amnt);
	
				#valid decryption	
				if ( $amnt =~ /^\d+(\.\d{1,2})?$/ ) {
					#check HMAC
					my $hmac = uc(hmac_sha1_hex($votehead . $votehead_parent . $amnt, $key));	
					if ( $hmac eq $rslts[3] ) {
						#did this to enable even parents
						#to record their budget amounts 
						if ( $votehead_parent eq "" ) {
							#may have been created by a child
							if (not exists $voteheads{lc($votehead)}) {
								$voteheads{lc($votehead)} = {"name" => $votehead, "income" => 0, "expenditure" => 0};
							}	
							$votehead_parent = $votehead;
						}
						else {
							$has_children++;
							$child_lookup{lc($votehead)} = lc($votehead_parent);
							if ($show_sub_categories) {
								#no risk of re-creating votehead
								$voteheads{lc($votehead)} = {"name" => $votehead, "income" => 0, "expenditure" => 0};
								
							}
							else {
								#don't want to re-create parent
								if (not exists $voteheads{lc($votehead_parent)}) {
									$voteheads{lc($votehead_parent)} = {"name" => $votehead_parent,  "income" => 0, "expenditure" => 0};
								}	
							}
						}
						${$votehead_hierarchy{lc($votehead_parent)}}{lc($votehead)}++;	
					}
				}
			}
		}
		else {
			print STDERR "Couldn't prepare SELECT FROM budget:", $prep_stmt2->errstr, $/;
		}
	}
	else {
		print STDERR "Couldn't prepare SELECT FROM budget:", $prep_stmt2->errstr, $/;
	}

	#income
	#all receipts+all arrears
	#use account_balance_updates 
	my $total_income = 0;

	my $prep_stmt10 = $con->prepare("SELECT account_name,amount,time,hmac FROM account_balance_updates");

	if ($prep_stmt10) {

		my $rc = $prep_stmt10->execute();

		if ($rc) {

			while ( my @rslts = $prep_stmt10->fetchrow_array() ) {

				my $account_name = remove_padding($cipher->decrypt($rslts[0]));
				my $amount = remove_padding($cipher->decrypt($rslts[1]));
				my $time = remove_padding($cipher->decrypt($rslts[2]));

				if ( $amount =~ /^\-?\d{1,10}(\.\d{1,2})?$/ ) {

					my $hmac = uc(hmac_sha1_hex($account_name . $amount . $time, $key));

					if ( $hmac eq $rslts[3] ) {
						
						#back possible
						if ( $time <= $stop_time ) {
	
							if ( $account_name =~ /\d+\-(.+)$/ ) {

								my $votehead = lc($1);
						
								#add to income
								if ( $show_sub_categories ) {
									${$voteheads{$votehead}}{"income"} += $amount;
								}
								else {
									if ( exists $child_lookup{$votehead} ) {
										$votehead = $child_lookup{$votehead};
										
									}
									${$voteheads{$votehead}}{"income"} += $amount;	
								}
								$total_income += $amount;
							}
						}
					}
				}	
			}

		}
		else {
			print STDERR "Couldn't execute SELECT FROM account_balance_updates: ", $prep_stmt10->errstr, $/;
		}	
	}
	else {
		print STDERR "Couldn't execute SELECT FROM account_balance_updates: ", $prep_stmt10->errstr, $/;
	}

	#payment of arrears will not
	#be recorded in account_balance_updates
	#check in cash_book for this payment
	my $prep_stmt4 = $con->prepare("SELECT receipt_votehead,votehead,amount,time,hmac FROM cash_book");

	if ($prep_stmt4) {

		my $rc = $prep_stmt4->execute();

		if ($rc) {

			while ( my @rslts = $prep_stmt4->fetchrow_array() ) {

				my $receipt_votehead = remove_padding($cipher->decrypt($rslts[0]));
				my $votehead = remove_padding($cipher->decrypt($rslts[1]));
				my $amount = remove_padding($cipher->decrypt($rslts[2]));
				my $time = remove_padding($cipher->decrypt($rslts[3]));

				#only use +ve payments
				#to avoid double counting when
				#I process account balances later
				if ( $amount =~ /^\d+(\.\d{1,2})?$/ ) {

					my $hmac = uc(hmac_sha1_hex($receipt_votehead . $votehead . $amount . $time, $key));
	
					if ( $hmac eq $rslts[4] ) {

						#within our search range
						if ( $time <= $stop_time ) {
							#only interested in payment of arrears
							next unless (lc($votehead) eq "arrears");
							#my $votehead_n = $votehead_lookup{$votehead};
							unless ($show_sub_categories) {
								if (exists $child_lookup{$votehead}) {
									$votehead = $child_lookup{$votehead};
								}
							}

							if ($amount >= 0) { 
								$voteheads{$votehead}->{"income"} += $amount;
								$total_income += $amount;
							}	
						}

					}	
				}
			}

		}
		else {
			print STDERR "Couldn't prepare SELECT FROM cash_book:", $prep_stmt4->errstr, $/;
		}
	}
	else {
		print STDERR "Couldn't prepare SELECT FROM cash_book:", $prep_stmt4->errstr, $/;
	}

	#prepayments
	my $total_prepayment = 0;
	my $prep_stmt7 = $con->prepare("SELECT account_name,class,amount,hmac FROM account_balances");
	
	if ($prep_stmt7) {

			my $rc = $prep_stmt7->execute();

			if ($rc) {
				my $cntr = 0;
				while (my @rslts = $prep_stmt7->fetchrow_array()) {

					my $decrypted_account_name = $cipher->decrypt($rslts[0]);
					my $decrypted_class = $cipher->decrypt($rslts[1]);
					my $decrypted_amount = $cipher->decrypt($rslts[2]);

					my $account_name = remove_padding($decrypted_account_name);
					my $class = remove_padding($decrypted_class);
					my $amount = remove_padding($decrypted_amount);

					#valid decryption
					#only interested in -ve balances
					if ( $amount =~ /^\-\d{1,10}(\.\d{1,2})?$/ ) {



						my $hmac = uc(hmac_sha1_hex($account_name . $class . $amount, $key));

						#auth the data
						if ( $hmac eq $rslts[3] ) {
						
							if ( $account_name =~ /^\d+\-arrears$/ ) {
								$total_prepayment += (-1 * $amount);
							}
						}
					}
				}
			}
			else {
				print STDERR "Couldn't execute SELECT FROM account_balances: ", $prep_stmt7->errstr, $/;
			}
	
	}
	else {
		print STDERR "Couldn't prepare SELECT FROM account_balances: ", $prep_stmt7->errstr, $/;
	}
	my $total_expenditure = 0;

	#read payments_book
	my $prep_stmt5 = $con->prepare("SELECT voucher_votehead,votehead,amount,time,hmac FROM payments_book");

	if ($prep_stmt5) {
					
		my $rc = $prep_stmt5->execute();

		if ($rc) {

			while ( my @rslts = $prep_stmt5->fetchrow_array() ) {

				my $voucher_votehead = remove_padding($cipher->decrypt($rslts[0]));
				my $votehead = remove_padding($cipher->decrypt($rslts[1]));
				my $amount = remove_padding($cipher->decrypt($rslts[2]));
				my $time = remove_padding($cipher->decrypt($rslts[3]));
				
				if ( $amount =~ /^\d+(?:\.\d{1,2})?$/ ) {

					my $hmac = uc(hmac_sha1_hex($voucher_votehead . $votehead . $amount . $time , $key));

					if ( $hmac eq $rslts[4] ) {


						if ( $time <= $stop_time ) {
	
							if ($show_sub_categories) {
								$voteheads{$votehead}->{"expenditure"} += $amount;
								$total_expenditure += $amount;
							}
							else {
								my $parent = $votehead;
								if (exists $child_lookup{$votehead}) {
									$parent = $child_lookup{$votehead};
								}
								$voteheads{$parent}->{"expenditure"} += $amount; 
								$total_expenditure += $amount;
							}
						}
					}
				}

			}

		}
		else {
			print STDERR "Couldn't prepare SELECT FROM payments_book:", $prep_stmt5->errstr, $/;
		}

	}
	else {
		print STDERR "Couldn't prepare SELECT FROM payment_book:", $prep_stmt5->errstr, $/;
	}

	#read commitments
	my $prep_stmt3 = $con->prepare("SELECT votehead,amount,time,hmac FROM budget_commitments");
	
	if ( $prep_stmt3 ) {

		my $rc = $prep_stmt3->execute();
		
		if ( $rc ) {

			while (my @rslts = $prep_stmt3->fetchrow_array()) {

				my $votehead = remove_padding($cipher->decrypt( $rslts[0] ));
				my $amount = remove_padding($cipher->decrypt( $rslts[1] ));
				my $time = remove_padding($cipher->decrypt( $rslts[2] ));

				if ( $amount =~ /^\d+(?:\.\d{1,2})?$/ ) {

					my $hmac = uc(hmac_sha1_hex($votehead . $amount . $time, $key));

					if ($hmac eq $rslts[3]) {
						
						if ($time <= $stop_time) {
	
							unless ( $show_sub_categories ) {
								if (exists $child_lookup{$votehead}) {
									$votehead = $child_lookup{$votehead};
								}
							}
							$voteheads{$votehead}->{"expenditure"} += $amount;
							$total_expenditure += $amount;
						}
					}

				}
			}

		}
		else {
			print STDERR "Couldn't execute SELECT FROM budget_commitments:", $prep_stmt3->errstr, $/;
		}
	}
	else {
		print STDERR "Couldn't prepare SELECT FROM budget_commitments:", $prep_stmt3->errstr, $/;
	}

	my $excess_income = "";
	my $excess_expenditure = ""; 

	my $income_table = qq!<TABLE border="1" cellspacing="5%" cellpadding="5%" style="vertical-align: middle"><THEAD>!;
	my $expenditure_table = qq!<TABLE border="1" cellspacing="5%" cellpadding="5%" style="vertical-align: middle"><THEAD>!;

	if ( $show_sub_categories ) {

		$income_table .= 
qq!
<TH>Votehead
<TH>Sub-category
<TH>Amount
</THEAD>
<TBODY>
!;

		$expenditure_table .= 
qq!
<TH>Votehead
<TH>Sub-category
<TH>Amount
</THEAD>
<TBODY>
!;

	}
	else {
		$income_table .= 
qq!
<TH>Votehead
<TH>Amount
</THEAD>
<TBODY>
!;

		$expenditure_table .= 
qq!
<TH>Votehead
<TH>Amount
</THEAD>
<TBODY>
!;

	}

	for my $votehead (sort {$a cmp $b} keys %votehead_hierarchy) {

		my ($colspan, $rowspan) = ("2", "1");

		my $sub_cat_val = "";	
		
		my $num_sub_categories = scalar(keys %{$votehead_hierarchy{$votehead}});	

		if ( $show_sub_categories and $num_sub_categories  > 1 ) {
			$colspan = "1";
			$rowspan = $num_sub_categories;	
			$sub_cat_val = qq!<TD style="font-weight: bold">Total!;
		}

		my $votehead_n = ${$voteheads{$votehead}}{"name"};

		my $income = format_currency($voteheads{$votehead}->{"income"});
		my $expenditure = format_currency($voteheads{$votehead}->{"expenditure"});

		$income_table .= qq!<TR><TD rowspan="$rowspan" colspan="$colspan">$votehead_n$sub_cat_val<TD>$income!;
		$expenditure_table .= qq!<TR><TD rowspan="$rowspan" colspan="$colspan">$votehead_n$sub_cat_val<TD>$expenditure! unless ($votehead eq "arrears");

		if ($show_sub_categories) {

			foreach ( keys %{$votehead_hierarchy{$votehead}} ) {

				next if ($_ eq $votehead);

				my $sub_cat_income = ${$voteheads{$_}}{"income"};
				my $sub_cat_expenditure = ${$voteheads{$_}}{"expenditure"};

				my $votehead_n = ${$voteheads{$_}}{"name"};

				$income_table .= qq!<TR><TD>$votehead_n<TD>$sub_cat_income!;
				$expenditure_table .= qq!<TR><TD>$votehead_n<TD>$sub_cat_expenditure!;
	
			}

		}
		
	}

	my $f_total_income = format_currency($total_income);
	my $f_total_expenditure = format_currency($total_expenditure);

	$income_table .= qq!<TR style="font-weight: bold"><TD colspan="2">TOTAL<TD>$f_total_income</TBODY></TABLE>!;
	$expenditure_table .= qq!<TR style="font-weight: bold"><TD colspan="2">TOTAL<TD>$f_total_expenditure</TBODY></TABLE>!;

	if ($total_expenditure > $total_income) {
		$excess_expenditure = "Excess of expenditure over income: " .format_currency($total_expenditure > $total_income);
	}

	else {
		$excess_income = "Excess of income over expenditure: " . format_currency($total_income - $total_expenditure);
	}

	my $f_total_prepayment = format_currency($total_prepayment);

	$content =
qq*
<!DOCTYPE html>
<html lang="en">

<head>
<title>Spanj::Accounts Management Information System::Create Income/Expenditure Statement</title>
</head>
<body>
$header
<p>
<H1>INCOME</H1>
$income_table
<h3>$excess_income</h3>
<p>
<H1>Expenditure</H1>
$expenditure_table
<h3>$excess_expenditure</h3>
<h3>Total prepayments: $f_total_prepayment</h3>
</body>
</html>
*;

	#my $cntr = 0;
	#for my $votehead (keys %voteheads) {
	#	print qq!X-Debug-! . $cntr++ . qq!: $votehead-> $voteheads{$votehead}->{"income"}\r\n!;
	#}
}
}

if (not $post_mode) {

	my @month_days = (31,28,31,30,31,30,31,31,30,31,30,31);

	my @today = localtime;

	my $month = $today[4] + 1;
	my $yr = $today[5] + 1900;

	if ( $yr % 4 == 0 ) {
		$month_days[1] = 29;
	}

	my $prev_month = $month - 1;
	
	#wind back
	if ($prev_month == 0) {
		$prev_month = 12;
		$yr--;
	}

	my $date = sprintf("%02d/%02d/%d", $month_days[$prev_month - 1], $prev_month, $yr);
 
	my $conf_code = gen_token();
	$session{"confirm_code"} = $conf_code;

	$content =
qq*

<!DOCTYPE html>
<html lang="en">

<head>
<title>Spanj::Accounts Management Information System::Create Income/Expenditure Statement</title>

<SCRIPT>

var date_re = /^([0-9][0-9]?)\*\\/\*([0-9][0-9]?)\*\\/\*(?:[0-9][0-9](?:[0-9][0-9])?)\*\$/;

function check_date(elem) {

	var date = document.getElementById(elem).value;
	var date_bts = date.match(date_re);

	if (date_bts) {
		var day = date_bts[1];
		if (day < 32) {
			var month = date_bts[2];
			if (month < 13) {	
				document.getElementById(elem + "_err").innerHTML = "";
			}
			else {
				document.getElementById(elem + "_err").innerHTML = "\*";
			}
		}
		else {
			document.getElementById(elem + "_err").innerHTML = "\*";
		}
	}
	else {
		document.getElementById(elem + "_err").innerHTML = "\*";
	}

}

</SCRIPT>
</head>

<body>
$header
$feedback

<FORM method="POST" action="/cgi-bin/income_expenditure.cgi">

<input type="hidden" name="confirm_code" value="$conf_code">

<TABLE cellspacing="5%" cellpadding="5%" style="text-align: left">

<TR><TH><LABEL for="date">Income/Expenditure as on</LABEL><TD><span style="color: red" id="date_err"></span><INPUT name="date" id="date" type="text" size="10" maxlength="10" value="$date" onkeyup="check_date('date')">
<TR><TH><LABEL style="font-weight: bold">Show votehead sub-categories</LABEL><TD><INPUT type="checkbox" name="show_sub_categories" checked value="1">
</TABLE>
<P><INPUT type="submit" name="view_print" value="View/Print">

</FORM>

</body>

</html>
*;

}

print "Status: 200 OK\r\n";
print "Content-Type: text/html; charset=UTF-8\r\n";

my $len = length($content);
print "Content-Length: $len\r\n";

my @new_sess_array = ();

for my $sess_key (keys %session) {
	push @new_sess_array, $sess_key."=".$session{$sess_key};        
}
my $new_sess = join ('&',@new_sess_array);

print "X-Update-Session: $new_sess\r\n";

print "\r\n";
print $content;
$con->disconnect() if (defined $con and $con);

sub gen_token {
	my @key_space = ("A","B","C","D","E","F","0","1","2","3","4","5","6","7","8","9");
	my $len = 5 + int(rand 15);
	if (@_ and ($_[0] eq "1")) {
		@key_space = ("A","B","C","D","E","F","G","H","J","K","L","M","N","P","T","W","X","Z","7","0","1","2","3","4","5","6","7","8","9");
		$len = 10 + int (rand 5);
	}
	my $token = "";
	for (my $i = 0; $i < $len; $i++) {
		$token .= $key_space[int(rand @key_space)];
	}
	return $token;
}

sub htmlspecialchars {
	my $cp = $_[0];
	$cp =~ s/&/&#38;/g;
        $cp =~ s/</&#60;/g;
        $cp =~ s/>/&#62;/g;
        $cp =~ s/'/&#39;/g;
        $cp =~ s/"/&#34;/g;
        return $cp;
}

sub remove_padding {

	return undef unless (@_);

	my $packed = $_[0];
	my @bytes = unpack("C*", $packed);
	
	my $final_index = $#bytes;
	my $pad_size = $bytes[$final_index];

	my $msg_valid = 1;
	#verify msg
	
	for ( my $i = 1; $i < $pad_size; $i++ ) {
		unless ( $bytes[$final_index - $i] == $pad_size ) {
			$msg_valid = 0;
			last;
		}
	}

	if ($msg_valid) {
		my $msg_size = ($final_index + 1) - $pad_size;
		my $msg = unpack("A${msg_size}", $packed);

		return $msg;
	}
	return undef;
}

sub add_padding {

	return undef unless (@_);

	my $tst_str = $_[0];
	my $tst_str_len = length($tst_str);

	my $rem = 16 - ($tst_str_len % 16);
	if ($rem == 0 ) {
		$rem = 16;
	}

	my @extras = ();
	for (my $i = 0; $i < $rem; $i++) {
		push @extras, $rem;
	}

	my $padded = pack("A${tst_str_len}C${rem}", $tst_str, @extras);
	return $padded;
}

sub format_currency {

	return "" unless (@_);

	my $formatted_num = $_[0];

	if ( $_[0] =~ /^(\-?)(\d+)(\.(?:\d))?$/ ) {

		my $sign = $1;
		my $shs = $2;
		my $cents = $3;

		$sign = "" if (not defined $sign);
		$cents = "" if (not defined $cents);

		my $num_blocks = int(length($shs) / 3);

		if ($num_blocks > 0) {

			my @nums = ();

			my $surplus = length($shs) % 3;
			if ($surplus > 0) {
				push @nums, substr($shs, 0, $surplus);
			}

			for (my $i = 0; $i < $num_blocks; $i++) {
				push @nums, substr($shs, $surplus + ($i * 3),3);
			}

			$formatted_num = join(",", @nums); 
		}

		$formatted_num = $sign . $formatted_num;
		$formatted_num .= $cents;
	}
	return $formatted_num;
}
