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
		#only bursar(user 2) and accountant(mod 17) can write payment vouchers
		if ($id eq "2" or ($id =~ /^\d+$/ and ($id % 17) == 0) ) {

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
	<p><a href="/">Home</a> --&gt; <a href="/accounts/">Accounts</a> --&gt; <a href="/cgi-bin/payment_vouchers.cgi">Write Payment Voucher</a>
	<hr> 
};

unless ($authd) {
	if ($logd_in) {
		my $err = qq!<p><span style="color: red">Sorry, you do not have the appropriate privileges to write a payment voucher.</span> Only the bursar and accountant(s) are authorized to take this action.!;

		#key issues?
		if ( $accountant ) {

			$err = qq!<p><span style="color: red">Sorry, could not obtain the encryption keys needed to manage accounts.</span> Try <a href="/cgi-bin/logout.cgi">logging out</a> and then log in again. If this problem persists, contact support.!;

		}

		$content .=
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj::Accounts Management Information System::Payment Vouchers</title>
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
		print "Location: /login.html?cont=/cgi-bin/payment_vouchers.cgi\r\n";
		print "Content-Type: text/html; charset=UTF-8\r\n";
       		my $res = 
qq!
<html lang="en">
<head>
<title>Spanj::Accounts Management Information System::Payment Vouchers</title>
</head>
<body>
$header
You should have been redirected to <a href="/login.html?cont=/cgi-bin/payment_vouchers.cgi">/login.html?cont=/cgi-bin/payment_vouchers.cgi</a>. If you were not, <a href="login.html?cont=/cgi-bin/payment_vouchers.cgi">Click Here</a> 
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
if ($post_mode) {

	#valid,non-automated request
	if ( not exists $auth_params{"confirm_code"} or not exists $session{"confirm_code"} or $auth_params{"confirm_code"} ne $session{"confirm_code"} ) {
		$feedback = qq!<span style="color: red">Invalid tokens sent.</span>!;
		$post_mode = 0;
		last PM;
	}

	my $paid_out_to = undef;
	#blank paid in by
	if (not exists $auth_params{"paid_out_to"} or $auth_params{"paid_out_to"} eq "") {
		$feedback = qq!<span style="color: red">You did not specify to whom this money was issued.</span>!;
		$post_mode = 0;
		last PM;
	}
	else {
		$paid_out_to = $auth_params{"paid_out_to"};
	}

	my %mode_payment_lookup = ("1" => "Bank Deposit", "2" => "Cash", "3" => "Banker's Cheque", "4" => "Money Order");

	my $mode_payment = undef;
	#invalid 'mode_payment'
	if (not exists $auth_params{"mode_payment"} or $auth_params{"mode_payment"} !~ /^[1-4]$/) {
		$feedback = qq!<span style="color: red">Invalid mode of payment specified.</span>!;
		$post_mode = 0;
		last PM;
	}
	else {
		$mode_payment = $auth_params{"mode_payment"};
	}

	my $ref_id = "";

	#banker's cheques/money orders must have a ref id
	if (($mode_payment eq "3" or $mode_payment eq "4")) {
		if ( not exists $auth_params{"ref_id"} or  $auth_params{"ref_id"} eq "" ) {
			$feedback = qq!<span style="color: red">You did not specify a ref no for this ! . ( $mode_payment eq "3" ? "cheque" : "money order" ). qq!</span>!;
			$post_mode = 0;
			last PM;
		}
		else {
			$ref_id = $auth_params{"ref_id"};
		}
	}

	my $description = "";
	if ( exists $auth_params{"description"} and length($auth_params{"description"}) < 56) {
		$description = $auth_params{"description"};
	}

	my $total_amnt = 0;
	my %voteheads = ();	
	my %commitments = ();

	my $credit_granted = 0;
	my $credit_repaid = 0;

	for my $auth_param (keys %auth_params) {

		if ( $auth_param =~ /^votehead_([1-5])$/ ) {

			my $id = $1;

			#votehead
			my $votehead = $auth_params{$auth_param};
			my $votehead_amnt = undef;

			#votehead amount
			if ( not exists $auth_params{"amount_votehead_$id"} or $auth_params{"amount_votehead_$id"} !~ /^\d{1,10}(\.\d{1,2})?$/ ) {
				next;
			}
			else {
				$votehead_amnt = $auth_params{"amount_votehead_$id"};
				$voteheads{$votehead} = $votehead_amnt;
				$total_amnt += $votehead_amnt;
			}

			#add creditors
			if ( exists $auth_params{"committed_amount_votehead_$id"} and $auth_params{"committed_amount_votehead_$id"} =~ /^\d{1,10}(\.\d{1,2})?$/ ) {
				#add -ve commitment
				#so that I can reuse the
				#code I use to deduct from
				#commitments
				
				my $committed_amnt = $auth_params{"committed_amount_votehead_$id"};
				$commitments{$votehead} += -$committed_amnt;

				#record creditor
				$credit_granted += $committed_amnt;
			}

			elsif ( exists $auth_params{"is_commitment_votehead_$id"} and $auth_params{"is_commitment_votehead_$id"} eq "1" ) {
				$commitments{$votehead} += $votehead_amnt;
	
				#record any credited amount repaid
				$credit_repaid += $votehead_amnt;	
			}

		}

	}

	unless ( scalar(keys %voteheads) > 0 ) {
		$feedback = qq!<span style="color: red">No valid votehead/amount specified.</span>!;
		$post_mode = 0;
		last PM;
	}

	my $votehead_str = join(",", keys %voteheads);
	my $time = time;
	my $voucher_no = undef;

	#write voucher
	my $prep_stmt3 = $con->prepare("INSERT INTO payment_vouchers VALUES(NULL,?,?,?,?,?,?,?,?)");

	if ($prep_stmt3) {

		my $enc_paid_out_to = $cipher->encrypt(add_padding($paid_out_to));
		my $enc_amount = $cipher->encrypt(add_padding($total_amnt));
		my $enc_mode_payment = $cipher->encrypt(add_padding($mode_payment));
		my $enc_ref_id = $cipher->encrypt(add_padding($ref_id));
		my $enc_descr = $cipher->encrypt(add_padding($description));
		my $enc_votehead = $cipher->encrypt(add_padding($votehead_str));
		my $enc_time = $cipher->encrypt(add_padding("".$time));

		my $hmac = uc(hmac_sha1_hex($paid_out_to . $total_amnt . $mode_payment . $ref_id . $description . $votehead_str . $time, $key));

		my $rc = $prep_stmt3->execute($enc_paid_out_to, $enc_amount, $enc_mode_payment, $enc_ref_id, $enc_descr, $enc_votehead, $enc_time, $hmac);

		if ($rc) {
			$voucher_no = $prep_stmt3->{mysql_insertid};

			#write to payments_book
			my $prep_stmt4 = $con->prepare("INSERT INTO payments_book VALUES(?,?,?,?,?)");
			if ($prep_stmt4) {
				for my $votehead (keys %voteheads) {
					my $enc_voucher_votehead = $cipher->encrypt(add_padding($voucher_no . "-" . $votehead));
					my $enc_votehead = $cipher->encrypt(add_padding($votehead));
					my $enc_amnt = $cipher->encrypt(add_padding($voteheads{$votehead}));
					my $hmac = uc(hmac_sha1_hex($voucher_no . "-" . $votehead . $votehead . $voteheads{$votehead} . $time, $key));
				
					my $rc = $prep_stmt4->execute($enc_voucher_votehead, $enc_votehead, $enc_amnt, $enc_time, $hmac);
					unless ($rc) {
						print STDERR "Couldn't execute INSERT INTO payments_book: ", $prep_stmt4->errstr, $/;
					}
				}
			}
			else {
				print STDERR "Couldn't prepare INSERT INTO payments_book: ", $prep_stmt4->errstr, $/;
			}

			#commitments
			if (scalar (keys %commitments) > 0) {

				my %new_commitments = ();
				my $prep_stmt3 = $con->prepare("SELECT votehead,amount,time,hmac FROM budget_commitments WHERE BINARY votehead=? LIMIT 1");
	
				if ( $prep_stmt3 ) {

					foreach (keys %commitments) {

						my $enc_votehead = $cipher->encrypt(add_padding($_));

						my $rc = $prep_stmt3->execute($enc_votehead);
						my $pre_existing_commitments = 0;

						if ( $rc ) {

							while ( my @rslts = $prep_stmt3->fetchrow_array() ) {

								my $votehead = remove_padding($cipher->decrypt( $rslts[0] ));
								my $amount = remove_padding($cipher->decrypt( $rslts[1] ));
								my $n_time = remove_padding($cipher->decrypt( $rslts[2] ));

								

								if ($amount =~ /^\d+(?:\.\d{1,2})?$/) {

									my $hmac = uc(hmac_sha1_hex($votehead . $amount . $n_time, $key));

									if ($hmac eq $rslts[3]) {
	
										$amount -= $commitments{$votehead};
										$amount = 0 if ($amount <= 0);	

										my $enc_amnt = $cipher->encrypt(add_padding($amount . ""));

										my $hmac = uc(hmac_sha1_hex($votehead . $amount . $time, $key));
 
										$new_commitments{$votehead} = {"votehead" => $enc_votehead, "amount" => $enc_amnt, "time" => $enc_time, "hmac" => $hmac};
										$pre_existing_commitments++;
									}
								}
							}
						}
	
						#if this commitment is being entered for the 1st time
						#create its data here
						if ( not $pre_existing_commitments and $credit_granted > 0 ) {

							my $enc_credit_granted = $cipher->encrypt(add_padding($credit_granted));
							my $hmac = uc(hmac_sha1_hex($_ . $credit_granted . $time, $key));

							$new_commitments{$_} = {"votehead" => $enc_votehead, "amount" => $enc_credit_granted, "time" => $enc_time, "hmac" => $hmac};
						}
					}
				}

				#update commitments
				if ( scalar(keys %new_commitments) > 0 ) {

					my $prep_stmt0 = $con->prepare("REPLACE INTO budget_commitments VALUES(?,?,?,?)");

					if ( $prep_stmt0 ) {

						for my $votehead (keys %new_commitments) {	
 							
							my $rc = $prep_stmt0->execute($new_commitments{$votehead}->{"votehead"}, $new_commitments{$votehead}->{"amount"}, $new_commitments{$votehead}->{"time"}, $new_commitments{$votehead}->{"hmac"});	
							unless ($rc) {
								print STDERR "Couldn't execute INSERT INTO budget_commitments: ", $prep_stmt0->errstr, $/;
							}
						}
					}
					else {
						print STDERR "Couldn't prepare INSERT INTO budget_commitments: ", $prep_stmt0->errstr, $/;
					}
				}
			}

			#record updates to creditors
			if ( $credit_repaid > 0 ) {

				#find the oldest creditor who matches our
				#'paid_out_to'

				my $prep_stmt4 = $con->prepare("SELECT creditor_id,creditor_name,description,amount,time,hmac FROM creditors WHERE BINARY creditor_name=? ORDER BY creditor_id ASC LIMIT 1");
	
				if ( $prep_stmt4 ) {

					my $enc_creditor_name = $cipher->encrypt(add_padding($paid_out_to));
					my $rc = $prep_stmt4->execute($enc_creditor_name);

					if ($rc) {

						while ( my @rslts = $prep_stmt4->fetchrow_array() ) {

							my $creditor_id = $rslts[0];
							my $creditor_name = remove_padding($cipher->decrypt( $rslts[1] ));
							my $description = remove_padding($cipher->decrypt( $rslts[2] ));
							my $amount = remove_padding($cipher->decrypt( $rslts[3] ));
							my $o_time = remove_padding($cipher->decrypt( $rslts[4] ));	

							if ($amount =~ /^\d+(?:\.\d{1,2})?$/) {

								my $hmac = uc(hmac_sha1_hex($creditor_name . $description . $amount . $o_time, $key));

								if ( $hmac eq $rslts[5] ) {
									my $n_credit = $amount - $credit_repaid;

									#do DELETE if debt has been fully repaid
									if ($n_credit <= 0) {

										my $prep_stmt5 = $con->prepare("DELETE FROM creditors WHERE creditor_id=? LIMIT 1");

										if ( $prep_stmt5 ) {

											my $rc = $prep_stmt5->execute($creditor_id);
											unless ($rc) {
												print STDERR "Couldn't execute SELECT FROM creditors: ", $prep_stmt5->errstr, $/;
											}

										}
										else {
											print STDERR "Couldn't prepare DELETE FROM creditors: ", $prep_stmt5->errstr, $/;
										}

									}

									#update creditor data
									else {

										my $prep_stmt6 = $con->prepare("UPDATE creditors SET amount=?,time=?,hmac=? WHERE creditor_id=? LIMIT 1");
										if ($prep_stmt6) {

											my $n_hmac = uc(hmac_sha1_hex($creditor_name . $description . $n_credit . $time, $key));
											my $enc_n_credit = $cipher->encrypt(add_padding("".$n_credit));

											my $rc = $prep_stmt6->execute($enc_n_credit, $enc_time, $n_hmac);

											unless ($rc) {
												print STDERR "Couldn't execute UPDATE creditors: ", $prep_stmt6->errstr, $/;
											}
									
										}
										else {
											print STDERR "Couldn't prepare UPDATE creditors: ", $prep_stmt6->errstr, $/;
										}
										
									} 
									
								}
							}
						}

					}
					else {
						print STDERR "Couldn't execute SELECT FROM creditors: ", $prep_stmt4->errstr, $/;
					}

					
				}
				else {
					print STDERR "Couldn't prepare SELECT FROM creditors: ", $prep_stmt4->errstr, $/;
				}

			}

			if ($credit_granted > 0) {

				my $prep_stmt7 = $con->prepare("INSERT INTO creditors VALUES(NULL,?,?,?,?,?)");

				if ($prep_stmt7) {

					my $enc_credit_granted = $cipher->encrypt(add_padding($credit_granted));

					my $hmac = uc(hmac_sha1_hex($paid_out_to . $description . $credit_granted . $time, $key));

					my $rc = $prep_stmt7->execute($enc_paid_out_to, $enc_descr, $enc_credit_granted, $enc_time, $hmac);

					unless ($rc) {
						print STDERR "Couldn't execute INSERT INTO creditors: ", $prep_stmt7->errstr, $/;
					}
				}
				else {
					print STDERR "Couldn't execute INSERT INTO creditors: ", $prep_stmt7->errstr, $/;
				}

			}

			#log action
			my @today = localtime;	
			my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];

			open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");

		       	if ($log_f) {
		       		@today = localtime;	
				my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];	
				flock ($log_f, LOCK_EX) or print STDERR "Could not log write payment voucher for $id due to flock error: $!$/"; 
				seek ($log_f, 0, SEEK_END);
				print $log_f "$id WRITE PAYMENT VOUCHER $voucher_no($total_amnt) $time\n";
				flock ($log_f, LOCK_UN);
		               	close $log_f;
		       	}
			else {
				print STDERR "Could not log write payment voucher for $id: $!\n";
			}

			$con->commit();

			my $ref_id_bt = "";
			my $ref_id_row = "";

			if ( $ref_id ne "" ) {
				$ref_id_row = qq!<TR><TD style="font-weight: bold">Ref No./Code<TD>$ref_id!;
				$ref_id_bt = "($ref_id)";
			}

			my $f_time = sprintf "%02d/%02d/%d %02d:%02d:%02d", $today[3],$today[4]+1,$today[5]+1900,$today[2],$today[1],$today[0];

			$paid_out_to = htmlspecialchars($paid_out_to);
			
			my @description_bts = split/,/, htmlspecialchars($description);
			my $description_list = join("<BR>", @description_bts);

			$description = htmlspecialchars($description);

			my $formatted_amount = format_currency($total_amnt);

			my ($shs,$cts) = ($total_amnt, "00");
			if ( $total_amnt =~ /^(\d+)(?:\.(\d{1,2}))$/ ) {
				$shs = $1;
				$cts = $2;
				if ( length ($cts) == 1 ) {
					$cts .= "0"; 
				}
			}

			my $votehead_rows = "";

			my @votehead_bts = ();

			for my $votehead (keys %voteheads) {

				my @this_votehead_bts = split/\s+/,$votehead;
				my @n_votehead_bts = ();

				foreach ( @this_votehead_bts ) {
					push @n_votehead_bts, ucfirst($_);
				}
				my $this_votehead = join(" ", @n_votehead_bts);

				my $amnt = $voteheads{$votehead};
				my ($shs,$cts) = ($amnt,"00");

				if ($amnt =~ /^(\d+)(?:\.(\d{1,2}))$/ ) {
					$shs = $1;
					$cts = $2;
					if ( length ($cts) == 1 ) {
						$cts .= "0"; 
					}
				}
					
				my $style = qq! style="border-bottom-style: none; border-top-style: none"!;	

				$votehead_rows .= qq!<TR><TD$style>$this_votehead<TD$style>&nbsp;<TD$style>&nbsp;<TD$style>&nbsp;<TD>$shs<TD>$cts!;
				if ( scalar (keys %voteheads) > 0 ) {
					$this_votehead .= "[" . format_currency($voteheads{$votehead}) . "]";
				}

				push @votehead_bts, $this_votehead;

			}

			my $votehead = join("<BR>", @votehead_bts);

			my $padded_paid_out_to = $paid_out_to . ("&nbsp;" x 75);
			my $dots = "." x 20;

			$content =
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj::Accounts Management Information System::Payment Vouchers</title>

<STYLE type="text/css">

\@media print {
	body {
		margin-top: 0px;
		margin-bottom: 0px;
		padding: 0px;
		font-size: 12pt;
		font-family: "Times New Roman", serif;	
	}

	div.no_header {
		display: none;
	}

	br.new_page {
		page-break-after: always;
	}

}

\@media screen {
	div.noheader {}	
}

</STYLE>
</head>
<body>
<div class="no_header">
$header
</div> 
<div style="height: 297mm; width: 210mm">
<div style="text-align: center; width: 210mm"><img src="/images/letterhead2.png" alt="" ></div>
<DIV style="text-align: center; text-decoration: underline;">PAYMENT VOUCHER</DIV>
<DIV style="text-align: right">Voucher No. <span style="font-weight: bold">$voucher_no</span></DIV>
<DIV style="text-align: center; font-weight: bold">MAIN ACCOUNT</DIV>
<HR>
<P><SPAN style="font-weight: bold">SECTION I</SPAN>
<p><span style="font-weight: bold">Payee's Name and Address</span>: <span style="text-decoration: underline">$padded_paid_out_to</span>

<TABLE style="table-layout: fixed; width: 200mm" border="1" cellpadding="0" cellspacing="0">

<tr style="font-weight: bold"><td style="width: 20%">Date<td style="width: 60%">Particulars<td style="width: 15%">Kshs<td style="width: 5%">Cts.
<tr style="height: 12em" valign="top"><td style="border-bottom-style: none">$f_time<td style="border-bottom-style: none">$description_list<td><td>
<tr><td style="border-top-style: none"><td style="border-top-style: none; text-align: right; font-weight: bold">TOTAL&nbsp;<td style="text-align: right">$shs<td style="text-align: right">$cts

</TABLE>
<p><span style="font-weight: bold">Mode Payment: </span>$mode_payment_lookup{"$mode_payment"}$ref_id_bt
<p><span style="font-weight: bold; text-decoration: underline">Payment Authorization</span>

<table style="table-layout: fixed; width: 200mm">

<tr><td style="width: 50%; height: 4em">Principal<br>$dots$dots<td style="width: 50%">Bursar/Accounts Clerk/Secretary<br>$dots$dots
<tr><td colspan="2" style="text-align: center">Date<br>$dots$dots$dots

</table>

<p style="line-height: 200%">In full payment of the following invoices/receipts: $dots $dots $dots $dots $dots $dots $dots $dots
<HR>
<P><SPAN style="font-weight: bold">SECTION II</SPAN>
<P>
<TABLE style="line-height: 200%; table-layout: fixed" border="1">
<THEAD>
<TH style="width: 25%">Votehead(s)<TH style="width: 25%">Details<TH style="width: 15%">C/B<TH style="width: 15%">L/F<TH style="width: 15%">Kshs<TH style="width: 5%">Cts
</THEAD>
<TBODY>
$votehead_rows
<TR><TD style="border-top-style: none"><TD style="border-top-style: none"><TD style="border-top-style: none"><TD style="border-top-style: none;font-weight: bold">TOTAL&nbsp;<TD style="font-weight: bold">$shs<TD style="font-weight: bold">$cts
</TBODY>
</TABLE>

<p style="line-height: 200%">Receieved this ....... day of ........ the year of ............. in payment of the above acccount<br>
the sum of.........................................................................................................
<TABLE style="width: 200mm; line-height: 200%">
<tr>
<TD>.......................................<br>Date<TD>.....................................<br>Signature of Witness<TD>......................................<br>Signature of Receiver
</TABLE>
</div>

</body>
</html>
*;
		}
		else {
			print STDERR "Couldn't execute INSERT INTO payment_vouchers: ", $prep_stmt3->errstr, $/;
		}
	}
	else {
		print STDERR "Couldn't prepare INSERT INTO payment_vouchers: ", $prep_stmt3->errstr, $/;
	}
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
<title>Spanj::Accounts Management Information System::Payment Vouchers</title>

<script type="text/javascript">

var num_re = /^([0-9]{0,10})(\\.([0-9]{0,2}))?\$/;
var left_padded_num = /^0+([^0]+.?\$)/;
var int_re = /^([0-9]+)/;
var num_re_full = /^[0-9]{1,10}(\\.[0-9]{1,2})?\$/;
var committed_amnt_re = /^committed_amount_votehead_([1-5])\$/;

function enable_ref_id() {
	var mode_payment = document.getElementById("mode_payment").value;
	if (mode_payment == 3 || mode_payment == 4) {
		document.getElementById("ref_id").disabled = false;
	}
	else {
		document.getElementById("ref_id").value = '';
		document.getElementById("ref_id").disabled = true;	
	}
}

function check_amount(elem) {

	var amnt = document.getElementById(elem).value;

	//disable 'deduct from commitments' if 
	//a new commitment is being entered

	var votehead_id = elem.match(committed_amnt_re);
	if (votehead_id) {

		var elem_id = "is_commitment_votehead_" + votehead_id[1];

		if (amnt.length > 0) {
			document.getElementById(elem_id).disabled = true;
		}
		else {
			document.getElementById(elem_id).disabled = false;
		}
	}

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
				if ( preceding_values && !blank_millions ) {
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
				if (preceding_values && !blank_thousands) {
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
				if (preceding_values && !blank_tens) {
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

		if (cents != null) {
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

		document.getElementById(elem + "_in_words").innerHTML = amnt_words;
		document.getElementById(elem + "_err").innerHTML = "";

		if (elem != 'total_amount') {
			var total = 0;
			for (var i = 1; i < 6; i++) {
				var amnt = document.getElementById("amount_votehead_" + i).value;
				if ( amnt.match(num_re_full) ) {
					total += parseFloat(amnt);
				}
			}

			if (total > 0) {
				document.getElementById('total_amount').value = total;
				check_amount('total_amount');
			}
		}
	}
	else {
		document.getElementById(elem + "_err").innerHTML = "\*";
		document.getElementById(elem + "_in_words").innerHTML = "";
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

function disable_new_commitments(votehead_id) {

	var deduct_from_commitments = document.getElementById("is_commitment_votehead_" + votehead_id).value;
	//disable
	if (deduct_from_commitments == 1) {
		document.getElementById("committed_amount_votehead_" + votehead_id).disabled = true;
	}
	//enable
	else {
		document.getElementById("committed_amount_votehead_" + votehead_id).disabled = false;
	}

}
</script>
</head>
<body>
$header
$feedback

<form method="POST" action="/cgi-bin/payment_vouchers.cgi">
<input type="hidden" name="confirm_code" value="$conf_code">
<table style="text-align: left">

<tr>
<th><label for="paid_out_to">Paid out to(e.g. Name/ID No.)</label>
<td><input type="text" name="paid_out_to" size="31" maxlength="31"> 

<tr>
<th><label for="mode_payment">Mode of Payment</label>
<td>
<select name="mode_payment" id="mode_payment" onchange="enable_ref_id()">
<option title="Bank Deposit" value="1">Bank Deposit</option>
<option selected title="Cash" value="2">Cash</option>
<option title="Banker's Cheque" value="3">Banker's Cheque</option>
<option title="Money Order" value="4">Money Order</option>
</select>

<tr style="font-style: italic">
<th><label for="ref_id">Ref no.(e.g. cheque no.)</label>
<td><input type="text" name="ref_id" disabled="1" size="20" maxlength="20" id="ref_id">

<tr>
<th>Being Payment for<br>(e.g. Qty of goods, service description)<td><input type="text" name="description" size="55" maxlength="55">

<tr style="font-style: italic">
<th><label for="amount">Total Amount</label>
<td><span style="color: red" id="total_amount_err"></span><input readonly type="text" name="total_amount" id="total_amount" size="12" maxlength="12">

<tr style="font-style: italic">
<th>Total amount in words:
<td><span id="total_amount_in_words"></span>

</table>
<p>
<table border="1" cellspacing="5%" cellpadding="5%">

<thead>
<th>Votehead
<th>Amount
<th style="font-style: italic">Amount in Words
<th>If this is a subsequent, partial payment<br>select \'Yes\' to deduct from commitments 
<th>If this is the first, partial payment<br>specify the amount committed(unpaid)
</thead>

<tbody>
<tr>
<td>
<select name="votehead_1">
$voteheads_select
</select>
<td><span style="color: red" id="amount_votehead_1_err"></span><input type="text" size="12" maxlength="12" autocomplete="off" onkeyup="check_amount('amount_votehead_1')" id="amount_votehead_1" name="amount_votehead_1">
<td><span id="amount_votehead_1_in_words" style="font-style: italic"></span>
<td><select onchange="disable_new_commitments(1)" name="is_commitment_votehead_1" id="is_commitment_votehead_1"><option title="No" value="0" selected>No</option><option title="Yes" value="1">Yes</option></select>
<td><LABEL for="committed_amount_votehead_1">Amount Committed:</LABEL>&nbsp;<span style="color: red" id="committed_amount_votehead_1_err"></span><input type="text" size="12" maxlength="12" autocomplete="off" onkeyup="check_amount('committed_amount_votehead_1')" id="committed_amount_votehead_1" name="committed_amount_votehead_1"><br><LABEL>Amount in words:</LABEL>&nbsp;<span id="committed_amount_votehead_1_in_words" style="font-style: italic"></span>

<tr>
<td>
<select name="votehead_2">
$voteheads_select
</select>
<td><span style="color: red" id="amount_votehead_2_err"></span><input type="text" size="12" maxlength="12" autocomplete="off" onkeyup="check_amount('amount_votehead_2')" id="amount_votehead_2" name="amount_votehead_2">
<td><span id="amount_votehead_2_in_words" style="font-style: italic"></span>
<td><select onchange="disable_new_commitments(2)" name="is_commitment_votehead_2" id="is_commitment_votehead_2"><option title="No" value="0" selected>No</option><option title="Yes" value="1">Yes</option></select>
<td><LABEL for="committed_amount_votehead_2">Amount Committed:</LABEL>&nbsp;<span style="color: red" id="committed_amount_votehead_2_err"></span><input type="text" size="12" maxlength="12" autocomplete="off" onkeyup="check_amount('committed_amount_votehead_2')" id="committed_amount_votehead_2" name="committed_amount_votehead_2"><br><LABEL>Amount in words:</LABEL>&nbsp;<span id="committed_amount_votehead_2_in_words" style="font-style: italic"></span>

<tr>
<td>
<select name="votehead_3">
$voteheads_select
</select>
<td><span style="color: red" id="amount_votehead_3_err"></span><input type="text" size="12" maxlength="12" autocomplete="off" onkeyup="check_amount('amount_votehead_3')" id="amount_votehead_3" name="amount_votehead_3">
<td><span id="amount_votehead_3_in_words" style="font-style: italic"></span>
<td><select onchange="disable_new_commitments(3)" name="is_commitment_votehead_3" id="is_commitment_votehead_3"><option title="No" value="0" selected>No</option><option title="Yes" value="1">Yes</option></select>
<td><LABEL for="committed_amount_votehead_3">Amount Committed:</LABEL>&nbsp;<span style="color: red" id="committed_amount_votehead_3_err"></span><input type="text" size="12" maxlength="12" autocomplete="off" onkeyup="check_amount('committed_amount_votehead_3')" id="committed_amount_votehead_3" name="committed_amount_votehead_3"><br><LABEL>Amount in words:</LABEL>&nbsp;<span id="committed_amount_votehead_3_in_words" style="font-style: italic"></span>

<tr>
<td>
<select name="votehead_4">
$voteheads_select
</select>
<td><span style="color: red" id="amount_votehead_4_err"></span><input type="text" size="12" maxlength="12" autocomplete="off" onkeyup="check_amount('amount_votehead_4')" id="amount_votehead_4" name="amount_votehead_4">
<td><span id="amount_votehead_4_in_words" style="font-style: italic"></span>
<td><select onchange="disable_new_commitments(4)" name="is_commitment_votehead_4" id="is_commitment_votehead_4"><option title="No" value="0" selected>No</option><option title="Yes" value="1">Yes</option></select>
<td><LABEL for="committed_amount_votehead_4">Amount Committed:</LABEL>&nbsp;<span style="color: red" id="committed_amount_votehead_4_err"></span><input type="text" size="12" maxlength="12" autocomplete="off" onkeyup="check_amount('committed_amount_votehead_4')" id="committed_amount_votehead_4" name="committed_amount_votehead_4"><br><LABEL>Amount in words:</LABEL>&nbsp;<span id="committed_amount_votehead_4_in_words" style="font-style: italic"></span>

<tr>
<td>
<select name="votehead_5">
$voteheads_select
</select>
<td><span style="color: red" id="amount_votehead_5_err"></span><input type="text" size="12" maxlength="12" autocomplete="off" onkeyup="check_amount('amount_votehead_5')" id="amount_votehead_5" name="amount_votehead_5">
<td><span id="amount_votehead_5_in_words" style="font-style: italic"></span>
<td><select onchange="disable_new_commitments(5)" name="is_commitment_votehead_5 id="is_commitment_votehead_5""><option title="No" value="0" selected>No</option><option title="Yes" value="1">Yes</option></select>
<td><LABEL for="committed_amount_votehead_5">Amount Committed:</LABEL>&nbsp;<span style="color: red" id="committed_amount_votehead_5_err"></span><input type="text" size="12" maxlength="12" autocomplete="off" onkeyup="check_amount('committed_amount_votehead_5')" id="committed_amount_votehead_5" name="committed_amount_votehead_5"><br><LABEL>Amount in words:</LABEL>&nbsp;<span id="committed_amount_votehead_5_in_words" style="font-style: italic"></span>

</tbody>
</table>
<p><input type="submit" name="save" value="Save">
</form>

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

	if ( $_[0] =~ /^(\-?)(\d+)(\.(?:\d{1,2}))?$/ ) {

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
