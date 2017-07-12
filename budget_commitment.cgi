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
	<p><a href="/">Home</a> --&gt; <a href="/accounts/">Accounts</a> --&gt; <a href="/cgi-bin/budget_commitment.cgi">Commitment</a>
	<hr> 
};

unless ($authd) {
	if ($logd_in) {
		my $err = qq!<p><span style="color: red">Sorry, you do not have the appropriate privileges to alter the fee structure.</span> Only the bursar and accountant(s) are authorized to take this action.!;

		#key issues?
		if ( $accountant ) {

			$err = qq!<p><span style="color: red">Sorry, could not obtain the encryption keys needed to manage accounts.</span> Try <a href="/cgi-bin/logout.cgi">logging out</a> and then log in again. If this problem persists, contact support.!;

		}

		$content .=
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj::Accounts Management Information System::Budget Commitment</title>
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
		print "Location: /login.html?cont=/cgi-bin/budget_commitment.cgi\r\n";
		print "Content-Type: text/html; charset=UTF-8\r\n";
       		my $res = 
qq!
<html lang="en">
<head>
<title>Spanj::Accounts Management Information System::Budget Commitment</title>
</head>
<body>
$header
You should have been redirected to <a href="/login.html?cont=/cgi-bin/budget_commitment.cgi">/login.html?cont=/cgi-bin/budget_commitment.cgi</a>. If you were not, <a href="login.html?cont=/cgi-bin/budget_commitment.cgi">Click Here</a> 
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

use Digest::HMAC_SHA1 qw/hmac_sha1_hex/;

PM: {
if ( $post_mode ) {

	#valid,non-automated request
	if ( not exists $auth_params{"confirm_code"} or not exists $session{"confirm_code"} or $auth_params{"confirm_code"} ne $session{"confirm_code"} ) {
		$feedback = qq!<span style="color: red">Invalid tokens sent.</span>!;
		$post_mode = 0;
		last PM;
	}

	#valid name
	if ( not exists $auth_params{"creditor_name"} or length($auth_params{"creditor_name"}) == 0 ) {
		$feedback = qq!<span style="color: red">No creditor name specified.</span>!;
		$post_mode = 0;
		last PM;
	}
	my $creditor_name = $auth_params{"creditor_name"};

	#valid description
	if ( not exists $auth_params{"description"} or length($auth_params{"description"}) == 0 ) {
		$feedback = qq!<span style="color: red">No description of the goods/service was provided.</span>!;
		$post_mode = 0;
		last PM;
	}
	my $description = $auth_params{"description"};

	#valid votehead
	if ( not exists $auth_params{"votehead"} or length($auth_params{"votehead"}) == 0 ) {
		$feedback = qq!<span style="color: red">No valid votehead specified.</span>!;
		$post_mode = 0;
		last PM;
	}

	my $votehead = $auth_params{"votehead"};
	
	#amount
	if ( not exists $auth_params{"amount"} or $auth_params{"amount"} !~ /^\d+(?:\.\d{1,2})?$/ ) {
		$feedback = qq!<span style="color: red">Invalid amount specified.</span>!;
		$post_mode = 0;
		last PM;
	}

	my $amount = $auth_params{"amount"};
	#duplicate amount
	#before past commitments are added
	#so that I can enter it into the creditors
	#table
	my $credited_amount = $amount;

	my $pre_existing = 0;

	my $prep_stmt3 = $con->prepare("SELECT votehead,amount,time,hmac FROM budget_commitments WHERE BINARY votehead=? LIMIT 1");
	
	if ( $prep_stmt3 ) {

		my $encd_votehead = $cipher->encrypt(add_padding($votehead));

		my $rc = $prep_stmt3->execute($encd_votehead);
		
		if ( $rc ) {

			while (my @rslts = $prep_stmt3->fetchrow_array()) {

				my $votehead = remove_padding($cipher->decrypt( $rslts[0] ));
				my $current_amount = remove_padding($cipher->decrypt( $rslts[1] ));
				my $time = remove_padding($cipher->decrypt( $rslts[2] ));

				if ($current_amount =~ /^\d+(?:\.\d{1,2})?$/) {
					
					my $hmac = uc(hmac_sha1_hex($votehead . $current_amount . $time, $key));
		
					if ($hmac eq $rslts[3]) {
						
						$amount += $current_amount;
					}
				}
			}	
		}
	}
	else {
		print STDERR "Couldn't prepare SELECT FROM budget_commitments: ", $prep_stmt3->errstr, $/;
	}

	
	my $prep_stmt0 = $con->prepare("REPLACE INTO budget_commitments VALUES(?,?,?,?)");

	if ( $prep_stmt0 ) {

		my $time = time . "";
		my $encd_votehead = $cipher->encrypt(add_padding($votehead));
		my $encd_amount = $cipher->encrypt(add_padding($amount));
		my $encd_time = $cipher->encrypt(add_padding($time));
	
		my $hmac = uc(hmac_sha1_hex($votehead . $amount . $time, $key));

		my $rc = $prep_stmt0->execute($encd_votehead, $encd_amount, $encd_time, $hmac);

		if ($rc) {

			my $prep_stmt7 = $con->prepare("INSERT INTO creditors VALUES(NULL,?,?,?,?,?)");

			if ($prep_stmt7) {

				my $encd_creditor_name = $cipher->encrypt(add_padding($creditor_name));
				my $encd_description = $cipher->encrypt(add_padding($description));
				my $encd_credited_amount = $cipher->encrypt(add_padding($credited_amount));
				my $hmac = uc(hmac_sha1_hex($creditor_name . $description . $credited_amount . $time, $key));

				my $rc = $prep_stmt7->execute($encd_creditor_name, $encd_description, $encd_credited_amount, $encd_time, $hmac);

				unless ($rc) {
					print STDERR "Couldn't execute INSERT INTO creditors: ", $prep_stmt7->errstr, $/;
				}

			}
			else {
				print STDERR "Couldn't execute INSERT INTO creditors: ", $prep_stmt7->errstr, $/;
			}

		}
		else {
			print STDERR "Couldn't execute INSERT INTO budget_commitments: ", $prep_stmt0->errstr, $/;
		}

	}

	else {
		print STDERR "Couldn't prepare INSERT INTO budget_commitments: ", $prep_stmt0->errstr, $/;
	}	

	#log action
	my @today = localtime;	
	my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];

	open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");

       	if ($log_f) {

       		@today = localtime;	
		my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];	
		flock ($log_f, LOCK_EX) or print STDERR "Could not log record budget commitment for $id due to flock error: $!$/"; 
		seek ($log_f, 0, SEEK_END);
		print $log_f "$id BUDGET COMMITMENT $votehead($amount) $time\n";
		flock ($log_f, LOCK_UN);
               	close $log_f;

       	}
	else {
		print STDERR "Could not log budget commitment $id: $!\n";
	}

	$con->commit();

	my $f_amnt_before = format_currency($auth_params{"amount"});
	my $f_amnt = format_currency($amount);

	my $escaped_votehead = htmlspecialchars($votehead);
	$feedback = qq!<span style="color: green">Budget commitment for $escaped_votehead (KSh $f_amnt_before) has been entered. </span>Total budget commitments for this votehead are <span style="font-weight: bold">$f_amnt</span>. Would you like to enter another budget commitment?!;

	$post_mode = 0;
	last PM; 
}
}

if (not $post_mode) {

	my $voteheads_select = "";

	my $prep_stmt4 = $con->prepare("SELECT votehead,votehead_parent,amount,hmac FROM budget");
	
	if ( $prep_stmt4 ) {

		my $rc = $prep_stmt4->execute();
		my %voteheads = ();

		if ( $rc ) {

			my %votehead_hierarchy;
			my $row_cntr = 0;
			while (my @rslts = $prep_stmt4->fetchrow_array()) {	
				$voteheads{$row_cntr++} = { "votehead" => $rslts[0], "parent_votehead" => $rslts[1], "amount" => $rslts[2], "hmac" => $rslts[3] };
			}

			for my $votehead_id (keys %voteheads) {

				my $decrypted_votehead = $cipher->decrypt( $voteheads{$votehead_id}->{"votehead"} );
				my $votehead = remove_padding($decrypted_votehead);
	
				my $decrypted_votehead_parent = $cipher->decrypt( $voteheads{$votehead_id}->{"parent_votehead"});
				my $votehead_parent = remove_padding($decrypted_votehead_parent);

				my $decrypted_amnt = $cipher->decrypt( $voteheads{$votehead_id}->{"amount"});	
				my $amnt = remove_padding($decrypted_amnt);

				#valid decryption
				if ( $amnt =~ /^\-?\d+(\.\d+)?$/ ) {
					#check HMAC
					my $hmac = uc(hmac_sha1_hex($votehead . $votehead_parent . $amnt, $key));	
					if ( $hmac eq ${$voteheads{$votehead_id}}{"hmac"} ) {
						#valid entry
						#top-level votehead
						#might have been created by its 
						#children so be careful no to overwrite
						#it.
						if ( $votehead_parent eq "" ) {
							if ( not exists $votehead_hierarchy{$votehead} ) {
								$votehead_hierarchy{$votehead} = {};
							}
						}
						else {	
							${$votehead_hierarchy{$votehead_parent}}{$votehead}++;
						}
					}
				}
			}

			for my $votehead ( keys %votehead_hierarchy ) {

				my $lc_votehead = lc($votehead);

				#does this votehead have any children?
				if ( scalar(keys %{$votehead_hierarchy{$votehead}} ) > 0 ) {

					$voteheads_select .= qq!<OPTGROUP label="$votehead">!;
					$voteheads_select .= qq!<OPTION value="$lc_votehead" title="$votehead">$votehead</OPTION>!;

					for my $sub_votehead ( keys %{$votehead_hierarchy{$votehead}} ) {
						my $lc_sub_votehead = lc($sub_votehead);
						$voteheads_select .= qq!<OPTION value="$lc_sub_votehead" title="$sub_votehead">$sub_votehead</OPTION>!;
					}
					$voteheads_select .= qq!</OPTGROUP>!;
				}
				else {
					
					$voteheads_select .= qq!<OPTION value="$lc_votehead" title="$votehead">$votehead</OPTION>!;
				}
			}
		}
		else {
			print STDERR "Couldn't execute SELECT FROM budget: ", $prep_stmt4->errstr, $/;
		}
	}
	else {
		print STDERR "Couldn't prepare SELECT FROM budget: ", $prep_stmt4->errstr, $/;
	}

	my $conf_code = gen_token();
	$session{"confirm_code"} = $conf_code;

	$content =
qq*

<!DOCTYPE html>
<html lang="en">

<head>
<title>Spanj::Accounts Management Information System::Budget Commitment</title>

<script type="text/javascript">

var num_re = /^([0-9]{0,10})(\\.([0-9]{0,2}))?\$/;
var left_padded_num = /^0+([^0]+.?\$)/;
var int_re = /^([0-9]+)/;

function check_amount() {

	var amnt = document.getElementById("amount").value;
	var match_groups = amnt.match(num_re);

	if ( match_groups ) {
		var shs = match_groups[1];
		var cents = match_groups[3];

		var unpadded_shs = shs.match(left_padded_num);
		if (unpadded_shs) {
			shs = unpadded_shs[1];
		}

		var shs_words = "";

		var shs_digits = shs.split("");
		var last_elem = (shs_digits.length) - 1;

		var tens_words = "";
		var hundreds_words = "";
		var thousands_words = "";
		var hundred_thousand_words = "";
		var millions_words = "";
		var hundred_million_words = "";
		var billions_words = "";

		var blank_millions = true;
		var blank_thousands = true;
		var blank_tens = true;

		if (last_elem > 0) {

			var tens = (shs_digits[last_elem - 1 ] + "" + shs_digits[last_elem]);	

			if (parseInt(tens) > 0) {
				blank_tens = false;

				if (parseInt(tens) < 10) {	
					var left_padding = tens.match(left_padded_num);
					if (left_padding) {
						tens = left_padding[1];
					}
						
					tens_words = get_num_in_words_ones(tens);
				}
				else if(parseInt(tens) < 20) {				
					tens_words = get_num_in_words_teens(tens)
				}
				else {	
					var ones = get_num_in_words_ones(shs_digits[last_elem]);
					var tens = get_num_in_words_tens(shs_digits[last_elem-1]);
	
					tens_words = tens + " " + ones;
				}

			}

			if (last_elem > 1) {

				var hundreds = get_num_in_words_ones(shs_digits[last_elem-2]);
				if (hundreds.length > 0) {
					hundreds_words = hundreds + " hundred ";
				}

				if (last_elem > 2) {

					var thousands = shs_digits[last_elem - 3];

					if (last_elem > 3) {
						thousands = shs_digits[last_elem - 4] + "" + thousands;
					}

					
					//alert("thousands: " + thousands + ".");
					if (parseInt(thousands) > 0) {
						blank_thousands = false;
						if (parseInt(thousands) < 10) {
	
							var left_padding = thousands.match(left_padded_num);
							if (left_padding) {
								thousands = left_padding[1];
							}
							thousands_words = get_num_in_words_ones(thousands) + " thousand";
						}
						else if (parseInt(thousands) < 20) {	
							thousands_words = get_num_in_words_teens(thousands) + " thousand";
						}
						else if (parseInt(thousands) >= 20) {	
						
							var ones = get_num_in_words_ones(shs_digits[last_elem - 3]);
							var tens = get_num_in_words_tens(shs_digits[last_elem - 4]);
	
							thousands_words = tens + " " + ones + " thousand";	
						}

					}
					if (last_elem > 4) {	
						var hundred_thousand = get_num_in_words_ones(shs_digits[last_elem-5]);	
						if ( hundred_thousand.length > 0 ) {
							hundred_thousand_words = hundred_thousand + " hundred";
						}
					}

					if (last_elem > 5) {

						var millions = shs_digits[last_elem - 6];

						if ( last_elem > 6 ) {
							millions = shs_digits[last_elem - 7] + "" + millions;
						}

						if (parseInt(millions) > 0) {

							blank_millions = false;

							if (parseInt(millions) < 10) {					
								var left_padding = millions.match(left_padded_num);
								if (left_padding) {
									millions = left_padding[1];
								}
								millions_words = get_num_in_words_ones(millions)  + " million";
							}
							else if (parseInt(millions) < 20) {
				
								millions_words = get_num_in_words_teens(millions) + " million";
							}
							else {
					
								var ones = get_num_in_words_ones(shs_digits[last_elem - 6]);
								var tens = get_num_in_words_tens(shs_digits[last_elem - 7]);
	
								millions_words = tens + " " + ones + " million";
							}
						}
					}

					if (last_elem > 7) {
						var hundred_million = get_num_in_words_ones(shs_digits[last_elem - 8]);
						if  ( hundred_million.length > 0 ) {
							hundred_million_words = hundred_million + " hundred";
						}

						if (last_elem > 8) {
							var billions = get_num_in_words_ones(shs_digits[last_elem - 9]);
							if (billions.length > 0) {
								billions_words = billions + " billion";
							}
						}
					}
				}
			}
			var preceding_values = 0;

			if (billions_words.length > 0) {
				shs_words += billions_words;
				preceding_values++;
			}
			if (hundred_million_words.length > 0) {
				if (preceding_values) {
					shs_words += ", ";
				}

				shs_words += hundred_million_words;
				if (blank_millions) {
					shs_words += " million";
				}
				preceding_values++;
			}
			if (millions_words.length > 0) {
				if ( preceding_values && \!blank_millions ) {
					shs_words += " and ";
				}
				shs_words += millions_words;
				preceding_values++;
			}
			if ( hundred_thousand_words.length > 0 ) {
				if (preceding_values) {
					shs_words += ", ";
				}
				shs_words += hundred_thousand_words;
				if (blank_thousands) {
					shs_words += " thousand";
				}
				preceding_values++;
			}
			if (thousands_words.length > 0) {	
				if (preceding_values && \!blank_thousands) {
					shs_words += " and ";
				}
				shs_words += thousands_words;
				preceding_values++;
			}
			if (hundreds_words.length > 0) {
				if ( preceding_values) {
					shs_words += ", ";
				}
				preceding_values++;
				shs_words += hundreds_words;
			}
			if (tens_words.length > 0) {
				if (preceding_values && \!blank_tens) {
					shs_words += " and ";
				}
				shs_words += tens_words;
			}

			shs_words += " shillings";
		}
		else {
			shs_words = get_num_in_words_ones(shs_digits[0]) + " shillings";
		}
		
		var amnt_words = shs_words;	

		if (cents \!= null) {
			var unpadded_cents = cents.match(left_padded_num);
			if ( unpadded_cents ) {
				cents = unpadded_cents[1]; 
			}
			var cents_words = "";
			if (cents < 10) {
				cents_words = get_num_in_words_ones(cents);
			}
			else if (cents < 20) {
				cents_words = get_num_in_words_teens(cents);
			}
			else {	
				var cents_bts = cents.split("");

				var ones = get_num_in_words_ones(cents_bts[1]);
				var tens = get_num_in_words_tens(cents_bts[0]);
	
				cents_words = tens + " " + ones;
			}
			amnt_words += " and " + cents_words + " cents";
		}
	
		amnt_words += ".";

		var first_char = amnt_words.substr(0,1);
		var uc_first_char = first_char.toUpperCase();

		var rest_str = amnt_words.substr(1);
		amnt_words = uc_first_char + rest_str;	

		document.getElementById("amount_in_words").innerHTML = amnt_words;
		document.getElementById("amount_err").innerHTML = "";
	}
	else {
		document.getElementById("amount_err").innerHTML = "\*";
		document.getElementById("amount_in_words").innerHTML = "";
	}

}

function get_num_in_words_ones(num) {
	switch (num) {
		case "0":
			return "";
		case "1":
			return "one";
		case "2":
			return "two";
		case "3":
			return "three";
		case "4":
			return "four";
		case "5":
			return "five";
		case "6":
			return "six";
		case "7":
			return "seven";
		case "8":
			return "eight";
		case "9":
			return "nine";
	}
	return "";
}

function get_num_in_words_teens(num) {
	switch (num) {
		case "10":
			return "ten";
		case "11":
			return "eleven";
		case "12":
			return "twelve";
		case "13":
			return "thirteen";
		case "14":
			return "fourteen";
		case "15":
			return "fifteen";
		case "16":
			return "sixteen";
		case "17":
			return "seventeen";
		case "18":
			return "eighteen";
		case "19":
			return "nineteen";
	}
	return "";
}

function get_num_in_words_tens(num) {
	switch (num) {	
		case "2":
			return "twenty";
		case "3":
			return "thirty";
		case "4":
			return "forty";
		case "5":
			return "fifty";
		case "6":
			return "sixty";
		case "7":
			return "seventy";
		case "8":
			return "eighty";
		case "9":
			return "ninety";
	}
	return "";
}
</script>
$header
$feedback

<FORM method="POST" action="/cgi-bin/budget_commitment.cgi">
<input type="hidden" name="confirm_code" value="$conf_code">
<TABLE cellspacing="5%" cellpadding="5%" style="text-align: left">
<TR><TH><LABEL for="creditor_name">Creditor Name</LABEL><TD><input type="text" name="creditor_name" size="31" maxlength="31">
<TR><TH><LABEL for="description">Description of Goods/service</LABEL><TD><input type="text" name="description" size="55" maxlength="55">
<TR><TH><LABEL for="votehead">Votehead</LABEL><TD><SELECT name="votehead">$voteheads_select</SELECT>
<TR><TH><LABEL for="amount">Amount</LABEL><TD><span id="amount_err" style="color: red"></span><INPUT type="text" name="amount" id="amount" value="" size="12" maxlength="12" onkeyup="check_amount()" onmousemove="check_amount()">
<TR style="font-style: italic"><TH><LABEL>Amount in words</LABEL><TD><span id="amount_in_words"></span>
</TABLE>
<INPUT type="submit" name="save" value="Save">
</FORM>
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
