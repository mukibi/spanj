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
		#only bursar(user 2) and accountant(mod 17) can prepare fee register
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
	<p><a href="/">Home</a> --&gt; <a href="/accounts/">Accounts</a> --&gt; <a href="/cgi-bin/fee_register.cgi">Prepare Fee Regiser</a>
	<hr> 
};

unless ($authd) {
	if ($logd_in) {
		my $err = qq!<p><span style="color: red">Sorry, you do not have the appropriate privileges to prepare the fee register.</span> Only the bursar and accountant(s) are authorized to take this action.!;

		#key issues?
		if ( $accountant ) {

			$err = qq!<p><span style="color: red">Sorry, could not obtain the encryption keys needed to manage accounts.</span> Try <a href="/cgi-bin/logout.cgi">logging out</a> and then log in again. If this problem persists, contact support.!;

		}

		$content .=
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj::Accounts Management Information System::Prepare Fee Register</title>
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
		print "Location: /login.html?cont=/cgi-bin/fee_register.cgi\r\n";
		print "Content-Type: text/html; charset=UTF-8\r\n";
       		my $res = 
qq!
<html lang="en">
<head>
<title>Spanj::Accounts Management Information System</title>
</head>
<body>
$header
You should have been redirected to <a href="/login.html?cont=/cgi-bin/fee_register.cgi">/login.html?cont=/cgi-bin/fee_register.cgi</a>. If you were not, <a href="login.html?cont=/cgi-bin/fee_register.cgi">Click Here</a> 
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

my $current_yr = (localtime)[5] + 1900;

PM: {
if ($post_mode) {

	unless ( exists $auth_params{"confirm_code"} and exists $session{"confirm_code"} and $auth_params{"confirm_code"} eq $session{"confirm_code"} ) {
		$feedback = qq!<span style="color: red">Invalid request.</span> Do not alter the hidden values in the HTML form.!;
		$post_mode = 0;
		last PM; 
	}

	my $fy = $current_yr;

	unless ( exists $auth_params{"fy"} and $auth_params{"fy"} =~ /^\d{4}$/ ) {
		$feedback = qq!<span style="color: red">Invalid financial year selected.</span>!;
		$post_mode = 0;
		last PM;
	}

	$fy = $auth_params{"fy"};

	my %selected_classes = ();

	for my $auth_param (keys %auth_params) {
		if ($auth_param =~ /^class_/) {
			$selected_classes{uc($auth_params{$auth_param})}++;	
		}
	}

	unless ( scalar(keys %selected_classes) > 0 ) {
		$feedback = qq!<span style="color: red">No classes selected. You must select atleast one class.</span>!;
		$post_mode = 0;
		last PM;
	}

	my %fees_for_the_year = ();

	#read fees structure
	my $prep_stmt = $con->prepare("SELECT value FROM vars WHERE id='2-fees for the year' LIMIT 1");

	if ($prep_stmt) {

		my $rc = $prep_stmt->execute();
		if ($rc) {

			while (my @rslts = $prep_stmt->fetchrow_array()) {

				my @fees_struct = split/;/, $rslts[0];

				for my $fees_struct (@fees_struct) {
					if ($fees_struct =~ /^([^:]+):(\d+\.?\d*)$/) {
						my $classes = $1;
						my $amnt = $2;

						my @classes_bts = split/,/,$classes;
						for my $class (@classes_bts) {
							$fees_for_the_year{uc($class)} = $amnt;
						}
					} 
				}

			}
		}

	}

	#get classes
	my %stud_rolls = ();
	my $prep_stmt1 = $con->prepare("SELECT table_name,class,start_year FROM student_rolls");
	
	if ($prep_stmt1) {

		my $rc = $prep_stmt1->execute();

		if ($rc) {

			while ( my @rslts = $prep_stmt1->fetchrow_array() ) {

				my $stud_yr = ($fy - $rslts[2]) + 1;

				if ($stud_yr > 0) {
					my $class = uc($rslts[1]);
					$class =~ s/\d+/$stud_yr/;
					
					if ( exists $selected_classes{$class} ) {
						$stud_rolls{$rslts[0]} = $class;
					}
				}

			}

		}
		else {
			print STDERR "Could not execute SELECT FROM student_rolls statement: ", $prep_stmt1->errstr, $/;
		}

	}

	else {
		print STDERR "Could not prepare SELECT FROM student_rolls statement: ", $prep_stmt1->errstr, $/;
	}


	unless (scalar (keys %stud_rolls) > 0) {
		$feedback = qq!<span style="color: red">No student rolls found.</span> Perhaps no student rolls have been created for the financial year selected.</span>!;
		$post_mode = 0;	
		last PM;
	}

	#read student rolls to obtain student data
	my %stud_data = ();

	for my $roll (keys %stud_rolls) {
		
		my $class = $stud_rolls{$roll};

		my $prep_stmt2 = $con->prepare("SELECT adm,s_name,o_names,house_dorm FROM `$roll`");

		if ($prep_stmt2) {

			my $rc = $prep_stmt2->execute();
			if ($rc) {

				while ( my @rslts = $prep_stmt2->fetchrow_array() ) {
					$stud_data{$rslts[0]} = {"class" => $class,"name" => $rslts[1] . " " .$rslts[2]};
				}

			}
			else {
				print STDERR "Could not execute SELECT FROM $roll statement: ", $prep_stmt2->errstr, $/;
			}
		}
		else {
			print STDERR "Could not prepare SELECT FROM $roll statement: ", $prep_stmt2->errstr, $/;
		}	
	}

	#should have seen some students
	unless ( scalar(keys %stud_data) ) {
		$feedback = qq!<span style="color: red">There are no students in the database matching the criteria you entered.</span>!;
		$post_mode = 0;
		last PM;
	}
	use Digest::HMAC_SHA1 qw/hmac_sha1_hex/;

	#read budget for voteheads
	my $con2 = DBI->connect("DBI:mysql:database=INFORMATION_SCHEMA;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});

	#which fee structures have ever been published
	my $prep_stmt11 = $con2->prepare("SELECT TABLE_NAME FROM TABLES WHERE TABLE_SCHEMA=? AND TABLE_NAME LIKE ?");

	my @budget_tables = ();

	if ($fy == $current_yr) {
		push @budget_tables, "budget";
	}

	if ($prep_stmt11) {

		my $rc = $prep_stmt11->execute($db, "budget_${fy}_%");

		if ($rc) {

			while ( my @rslts = $prep_stmt11->fetchrow_array() ) {
				push @budget_tables, $rslts[0];
			}

		}
		else {
			print STDERR "Couldn't execute SELECT FROM INFORMATION_SCHEMA.TABLES: ", $prep_stmt11->errstr, $/;
		}
	}
	else {
		print STDERR "Couldn't execute SELECT FROM INFORMATION_SCHEMA.TABLES: ", $prep_stmt11->errstr, $/;
	}
	my %voteheads = ("arrears" => "Arrears");

	for my $budget_table (@budget_tables) {

		#read budget
		my $prep_stmt9 = $con->prepare("SELECT votehead,votehead_parent,amount,hmac FROM $budget_table");
	
		if ($prep_stmt9) {
	
			my $rc = $prep_stmt9->execute();
			if ($rc) {
				while ( my @rslts = $prep_stmt9->fetchrow_array() ) {
						
					my $decrypted_votehead = $cipher->decrypt($rslts[0]);
					my $decrypted_votehead_parent = $cipher->decrypt($rslts[1]);	
					my $decrypted_amount = $cipher->decrypt($rslts[2]);

					my $votehead_n = remove_padding($decrypted_votehead);
					my $votehead_parent = remove_padding($decrypted_votehead_parent);	
					my $amount = remove_padding($decrypted_amount);
	
					#valid decryption
					if ( $amount =~ /^\-?\d{1,10}(\.\d{1,2})?$/ ) {

						my $hmac = uc(hmac_sha1_hex($votehead_n . $votehead_parent . $amount, $key));
								
						#auth the data
						if ( $hmac eq $rslts[3] ) {
							$voteheads{lc($votehead_n)} = $votehead_n;
						}
					}
				}
			}
			else {
				print STDERR "Couldn't execute SELECT FROM budget: ", $prep_stmt9->errstr, $/;
			}
		}
		else {
			print STDERR "Couldn't prepare SELECT FROM budget: ", $prep_stmt9->errstr, $/;
		}
	}

	#reverse lookup of account names to
	#adms
	my %account_adm_lookup = ();

	for my $stud (keys %stud_data) {
		for my $votehead (keys %voteheads) {
			$account_adm_lookup{$stud . "-" . $votehead} = $stud;
		}
	}
	
	use Time::Local;
	my ($start_time, $end_time) = (0,0);

	$start_time = timelocal(0,0,0,1,0,$fy);
	$end_time = timelocal(59,59,23,31,11,$fy);

	
	#calculate fees expected
	#all account_balance_updates entries
	#between $start_time and $end_time are
	#added up for each student to establish the
	#total fees expected
	my %fees_expected = ();
	
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
						
						#time must be between $start_time and $end_time
						if ($time >= $start_time and $time <= $end_time) {

							#print "X-Debug-0: valid time\r\n";
							#student must be in filter
							if ( exists $account_adm_lookup{$account_name} ) {

								#print "X-Debug-1: valid stud\r\n";

								my $adm = $account_adm_lookup{$account_name};
								my $votehead = substr($account_name, length($adm) + 1);

								$fees_expected{$adm}->{$votehead} += $amount;

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

	my %arrears = ();

	my $prep_stmt7 = $con->prepare("SELECT account_name,class,amount,hmac FROM account_balances WHERE BINARY account_name=? LIMIT 1");
	
	if ($prep_stmt7) {

		for my $adm (keys %stud_data) {

			$arrears{$adm} = 0;
	
			my $encd_accnt_name = $cipher->encrypt(add_padding($adm . "-arrears"));

			my $rc = $prep_stmt7->execute($encd_accnt_name);

			if ( $rc ) {

				while ( my @rslts = $prep_stmt7->fetchrow_array() ) {

					my $decrypted_account_name = $cipher->decrypt($rslts[0]);
					my $decrypted_class = $cipher->decrypt($rslts[1]);
					my $decrypted_amount = $cipher->decrypt($rslts[2]);

					my $account_name = remove_padding($decrypted_account_name);
					my $class = remove_padding($decrypted_class);
					my $amount = remove_padding($decrypted_amount);

					#valid decryption
					if ( $amount =~ /^\-?\d{1,10}(\.\d{1,2})?$/ ) {

						my $hmac = uc(hmac_sha1_hex($account_name . $class . $amount, $key));

						#auth the data
						if ( $hmac eq $rslts[3] ) {		
							$arrears{$adm} = $amount;
							$fees_expected{$adm}->{"arrears"} += $amount;
						}
					}
				}
			}
			else {
				print STDERR "Couldn't execute SELECT FROM account_balances: ", $prep_stmt7->errstr, $/;
			}
		}
	}
	else {
		print STDERR "Couldn't prepare SELECT FROM account_balances: ", $prep_stmt7->errstr, $/;
	}

	my @receipt_tables = ();
	my $max_quarter = 0;

	if ($prep_stmt11) {

		my $rc = $prep_stmt11->execute($db, "receipts_${fy}_%");

		if ($rc) {

			while ( my @rslts = $prep_stmt11->fetchrow_array() ) {
				push @receipt_tables, $rslts[0];
				if ( $rslts[0] =~ /_(\d+)$/ ) {
					my $quarter = $1;
					if ( $quarter > $max_quarter ) {
						$max_quarter = $quarter;
					}
				}
			}

		}
		else {
			print STDERR "Couldn't execute SELECT FROM INFORMATION_SCHEMA.TABLES: ", $prep_stmt11->errstr, $/;
		}
	}
	else {
		print STDERR "Couldn't execute SELECT FROM INFORMATION_SCHEMA.TABLES: ", $prep_stmt11->errstr, $/;
	}
	#read receipts

	#if processing current FY, first include
	#the current receipt table
	if ( $fy == $current_yr ) {
		push @receipt_tables, "receipts";
	}
	
	#verify tables
	my %verified_receipt_tables = ();

	my $prep_stmt12 = $con2->prepare("SELECT COLUMN_NAME FROM COLUMNS WHERE TABLE_SCHEMA=? AND TABLE_NAME=?");

	if ($prep_stmt12) {

		for my $table (@receipt_tables) {

			#which fee structures have ever been published
			my $rc = $prep_stmt12->execute($db,$table);
			if ($rc) {

				my %cols = ();
				while ( my @rslts = $prep_stmt12->fetchrow_array() ) {
					$cols{lc($rslts[0])}++;
				}

				if ( scalar(keys %cols) == 9 and exists $cols{"receipt_no"} and exists $cols{"paid_in_by"} and exists $cols{"class"} and exists $cols{"amount"} and exists $cols{"mode_payment"}  and exists $cols{"ref_id"} and exists $cols{"votehead"} and exists $cols{"time"} and exists $cols{"hmac"} ) {
					my $table_index = $max_quarter + 1;
					if ($table =~ /_(\d+)$/) {
						$table_index = $1;
					}
					$verified_receipt_tables{$table} = $table_index;
				}
			}
			else {
				print STDERR "Couldn't execute SELECT FROM INFORMATION_SCHEMA.COLUMNS: ", $prep_stmt12->errstr, $/;
			}
		}

	}
	else {
		print STDERR "Couldn't execute SELECT FROM INFORMATION_SCHEMA.COLUMNS: ", $prep_stmt12->errstr, $/;
	}

	my %receipt_to_adm = ();
	my %adm_to_receipts = ();	
	my %receipt_times = ();

	#read receipts
	for my $table_3 (keys %verified_receipt_tables) {

		#read receipts
		my $prep_stmt8 = $con->prepare("SELECT receipt_no,paid_in_by,class,amount,mode_payment,ref_id,votehead,time,hmac FROM $table_3");

		if ($prep_stmt8) {

			my $rc = $prep_stmt8->execute();

			if ($rc) {

				while ( my @rslts = $prep_stmt8->fetchrow_array() ) {

					my $receipt_no = $rslts[0];
					my $paid_in_by = remove_padding($cipher->decrypt($rslts[1]));
					my $class = remove_padding($cipher->decrypt($rslts[2]));
					my $amount = remove_padding($cipher->decrypt($rslts[3]));
					my $mode_payment = remove_padding($cipher->decrypt($rslts[4]));
					my $ref_id = remove_padding($cipher->decrypt($rslts[5]));
 					my $votehead = remove_padding($cipher->decrypt($rslts[6]));
					my $time = remove_padding($cipher->decrypt($rslts[7]));

					if ( $amount =~ /^\d{1,10}(\.\d{1,2})?$/ ) {

						my $hmac = uc(hmac_sha1_hex($paid_in_by . $class . $amount . $mode_payment . $ref_id . $votehead . $time, $key));
						if ( $hmac eq $rslts[8] ) {
							#just to be sure, verify the time
							if ($time >= $start_time and $time <= $end_time) {
								#only look at students in our filter
								if ( exists $stud_data{$paid_in_by} ) {
									$receipt_to_adm{$table_3}->{$receipt_no} = $paid_in_by;
									$adm_to_receipts{$table_3}->{$paid_in_by}->{$receipt_no}++;
									$receipt_times{$table_3}->{$receipt_no} = $time;
								}

							}
						}
					}
				}
			}
			else {
				print STDERR "Couldn't execute SELECT FROM $table_3: ", $prep_stmt8->errstr, $/;
			}

		}
		else {
			print STDERR "Couldn't execute SELECT FROM $table_3: ", $prep_stmt8->errstr, $/;
		}
	}

	#read cash_books to correlate receipt nos and voteheads
	my %receipt_voteheads = ();

	for my $table_4 (keys %verified_receipt_tables) {

		my $cash_book_table = $table_4;
		$cash_book_table =~ s/receipts/cash_book/;

		#read receipts
		my $prep_stmt8 = $con->prepare("SELECT receipt_votehead,votehead,amount,time,hmac FROM $cash_book_table");

		if ($prep_stmt8) {

			my $rc = $prep_stmt8->execute();

			if ($rc) {

				while ( my @rslts = $prep_stmt8->fetchrow_array() ) {

					my $receipt_votehead = remove_padding($cipher->decrypt($rslts[0]));
					my $votehead = remove_padding($cipher->decrypt($rslts[1]));
					my $amount = remove_padding($cipher->decrypt($rslts[2]));
					my $time = remove_padding($cipher->decrypt($rslts[3]));

					#allow negative amounts to handle overpayments as a credit
					if ( $amount =~ /^\-?\d+(\.\d{1,2})?$/ ) {

						my $hmac = uc(hmac_sha1_hex($receipt_votehead . $votehead . $amount . $time, $key));
	
						if ( $hmac eq $rslts[4] ) {
							
							my $rcpt_no = undef;

							if ( $receipt_votehead =~ /^(\d+)\-/ ) {
								$rcpt_no = $1;
							}

							elsif ( $receipt_votehead =~ /^(Prepayment\((\d+)\-\d+\))\-/ ) {

								$rcpt_no = $1;
								my $adm  = $2;

								#within our time scope
								if ( $time >= $start_time and $time <= $end_time ) {

									$receipt_to_adm{$table_4}->{$rcpt_no} = $adm;
									$adm_to_receipts{$table_4}->{$adm}->{$rcpt_no}++;
									$receipt_times{$table_4}->{$rcpt_no} = $time;
								}

							}

							#within our time scope
							if ( $time >= $start_time and $time <= $end_time ) {
								if ( defined($rcpt_no) ) {

									$receipt_voteheads{$table_4}->{$rcpt_no}->{$votehead} = $amount;
								}
							
							}

							#add up all arrears payments made after 
							#the start of the financial year under review
							if ( $time >= $start_time ) {
								if ( $votehead eq "arrears" ) {
									my $adm = $receipt_to_adm{$table_4}->{$rcpt_no};
									$fees_expected{$adm}->{"arrears"} += $amount;
								}
							}

						}
					}
				}
			}
			else {
				print STDERR "Couldn't prepare SELECT FROM cash_book:", $prep_stmt8->errstr, $/;
			}
		}
		else {
			print STDERR "Couldn't prepare SELECT FROM cash_book:", $prep_stmt8->errstr, $/;
		}

	}

	my $results = "";
	my $spaces = "&nbsp;" x 10;

	for my $stud (sort {$a <=> $b} keys %stud_data) {

		my $fees_for_the_yr = format_currency($fees_for_the_year{$stud_data{$stud}->{"class"}});

		my $stud_arrears = format_currency($arrears{$stud});

		if ($arrears{$stud} < 0) {
			my $arrears_abs = format_currency(-1 * $arrears{$stud});
			$stud_arrears = qq!($arrears_abs)!;
		}

		$results .= qq!<DIV style="width: 210mm; text-align: center">!;
		#logo
		$results .= qq!<p><img src="/images/letterhead2.png" alt="" href="/images/letterhead2.png" style="padding: 0px 0px 0px 0px; margin: 0px 0px 0px 0px">!;
		#header

		$results .= qq!<P><SPAN style="font-size: 1.2em; font-weight: bold">FEES REGISTER&nbsp;</SPAN><SPAN style="text-decoration: underline">$spaces</SPAN>&nbsp;<SPAN style="font-size: 1.2em; font-weight: bold">FEES FOR THE YEAR&nbsp;</SPAN><SPAN style="text-decoration: underline">&nbsp;&nbsp;$fees_for_the_yr$spaces</SPAN><SPAN style="font-size: 1.2em; font-weight: bold">ARREARS</SPAN>&nbsp;<SPAN style="background-color: black; color: white">&nbsp;$fees_expected{$stud}->{"arrears"}&nbsp;</span>!;

		$results .= qq!<P><SPAN style="font-size: 1.2em; font-weight: bold">STUDENT NAME</SPAN>&nbsp;<SPAN style="text-decoration: underline">$stud_data{$stud}->{"name"}&nbsp;</SPAN><SPAN style="font-size: 1.2em; font-weight: bold">CLASS</SPAN>&nbsp;<SPAN style="text-decoration: underline">$stud_data{$stud}->{"class"}&nbsp;</SPAN><SPAN style="font-size: 1.2em; font-weight: bold">ADMISSION NO</SPAN>&nbsp;<SPAN style="text-decoration: underline">$stud</SPAN>!;


		$results .= "<P>";
		$results .= qq!<TABLE border="1" style="margin: 3">!;

		$results .= qq!<THEAD>!;
		#voteheads
		$results .= qq!<TH colspan="2"><div><span>VOTEHEADS</span></div>!;

		for my $votehead (sort {$a cmp $b} keys %voteheads) {
			$results .= qq!<TH class="rotate"><div><span>$voteheads{$votehead}</span></div>!;
		}

		#total
		$results .= qq!<TH class="rotate"><div><span>TOTAL</span></div>!;
		#blank
		$results .= qq!<TH class="rotate"><div><span>&nbsp;</span></div>!;

		$results .= "<TR>";
		
		#total fees expected
		$results .= qq!<TH colspan="2">TOTAL FEES EXPECTED!;
		
		my $total_fees_expected = 0;

		for my $votehead (sort {$a cmp $b} keys %voteheads) {
			my $amnt = 0;
			if (exists $fees_expected{$stud}->{$votehead}) {
				$amnt = $fees_expected{$stud}->{$votehead};
			}
			$total_fees_expected += $amnt;
		
			my $f_amnt = format_currency($amnt);

			$results .= qq!<TH>$f_amnt!;
		}

		my $f_total_fees_expected = format_currency($total_fees_expected);
		$results .= qq!<TH>$f_total_fees_expected!;
		$results .= qq!<TH>&nbsp;!;

		$results .= qq!<TR><TH>Date<TH>Receipt No.!;
		for my $votehead (sort {$a cmp $b} keys %voteheads) {
			$results .= qq!<TH>&nbsp;!;
		}
		$results .= qq!<TH>&nbsp;<TH>&nbsp;!;
	
		$results .= qq!</THEAD>!;

		$results .= qq!<TBODY>!;

		my $num_rows = 0;

		my %votehead_totals = ();

		for my $votehead ( keys %voteheads ) {

			$votehead_totals{$votehead} = 0;

		}
		for my $table (sort { $verified_receipt_tables{$a} <=> $verified_receipt_tables{$b} } keys %verified_receipt_tables) {

			
			for my $receipt ( sort { $receipt_times{$table}->{$a} <=> $receipt_times{$table}->{$b} }  keys %{$adm_to_receipts{$table}->{$stud}} ) {
				my @time_then = localtime($receipt_times{$table}->{$receipt});
				my $formatted_time = sprintf ("%02d/%02d/%d", $time_then[3],$time_then[4]+1,$time_then[5]+1900);

				my $f_receipt = $receipt;

				if ($receipt =~ /^Prepayment/) {
					$f_receipt = "Prepayment";
				}

				$results .= qq!<TR><TD>$formatted_time<TD>$f_receipt!;

				my $receipt_total = 0;
				for my $votehead (sort {$a cmp $b} keys %voteheads) {
					my $amount = 0;

					if (exists $receipt_voteheads{$table}->{$receipt}->{$votehead}) {
						$amount = $receipt_voteheads{$table}->{$receipt}->{$votehead};
					}

					$receipt_total += $amount;
					$votehead_totals{$votehead} += $amount;

					$amount = format_currency($amount);

					$results .= qq!<TD>$amount!;
				}
		
				$results .= qq!<TD style="font-weight: bold">$receipt_total<TD>&nbsp;!;

				$num_rows++;
			}
		}

		#blank rows;
		my $num_blanks = 4 + scalar(keys %voteheads);

		if ($num_rows < 20) {

			for ( my $i = 0; $i < (20 - $num_rows); $i++ ) {

				$results .= qq!<TR>!;
				foreach (1..$num_blanks) {
					$results .= qq!<TD>&nbsp;!;
				}

			}
		}

		#row total
		$results .= qq!<TR style="font-weight: bold"><TD colspan="2">TOTAL!;

		my $total_total = 0;

		for my $votehead1 ( sort {$a cmp $b} keys %voteheads ) {
			$total_total += $votehead_totals{$votehead1};
			$results .= qq!<TD>! . format_currency($votehead_totals{$votehead1});
		}

		$results .= qq!<TD>$total_total<TD>&nbsp;!;
	
		$results .= qq!<TR style="font-weight: bold"><TD colspan="2">OUTSTANDING BALANCE!;
		my $total_outstanding = 0;

		for my $votehead2 ( sort {$a cmp $b} keys %voteheads ) {
			my $diff = $fees_expected{$stud}->{$votehead2} - $votehead_totals{$votehead2};
			$total_outstanding += $diff;
			$results .= qq!<TD>! . format_currency($diff);	
		}

		my $f_total_outstanding = format_currency($total_outstanding);
	
		$results .= qq!<TD>$f_total_outstanding<TD>&nbsp;!;
		$results .= qq!</TBODY>!;

		$results .= qq!</TABLE>!;
		#new page
		$results .= qq!<BR class="new_page">!;
		$results .= qq!</DIV>!;

		
	}

	my $longest_votehead = 100;

	for my $votehead2 ( keys %voteheads ) {
		my $px_len = length($votehead2) * 15;
		if ($px_len > $longest_votehead) {
			$longest_votehead = $px_len;
		}
	}

	$content = 
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj::Accounts Management Information System::Fee Statement</title>

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
	br.new_page {}
}

th.rotate {
	height: ${longest_votehead}px;
	white-space: nowrap;
	
}

th.rotate > div {
	transform:
		rotate(270deg)
		translate(-140px,0px);
	width: 30px;
}

th.rotate > div > span {
	border-bottom: 1px solid #ccc;	
	margin: 1em;
}

</STYLE>
</head>
<body>
<div class="no_header">
$header
</div>
$results
</body>
</html>
*;

	
	#log download
	my @today = localtime;	
	my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];

	open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");
      	if ($log_f) {

		my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
		flock ($log_f, LOCK_EX) or print STDERR "Could not log view fee register for $id due to flock error: $!$/";
		seek ($log_f, 0, SEEK_END);	
 
		print $log_f "$id VIEW FEE REGISTER  $time\n";
		flock ($log_f, LOCK_UN);
          	close $log_f;
      	 }
	else {
		print STDERR "Could not log view fee register $id: $!\n";
	}

}
}

if (not $post_mode) {

	my %grouped_classes = ("1"=> "1", "2"=> "2", "3"=> "3","4"=> "4");
	
	my $prep_stmt = $con->prepare("SELECT value FROM vars WHERE id='1-classes' LIMIT 1");

	if ($prep_stmt) {
		my $rc = $prep_stmt->execute();
		if ($rc) {
			while (my @rslts = $prep_stmt->fetchrow_array()) {
				my @classes = split/,/, $rslts[0];
				%grouped_classes = ();
				for my $class (@classes) {
					if ($class =~ /(\d+)/) {	
						$grouped_classes{$1}->{$class}++;
					}
				}
			}
		}
	}

	my $classes_select = qq!<TABLE cellpadding="5%" cellspacing="5%"><TR>!;
	for my $class_yr (sort {$a <=> $b} keys %grouped_classes) {
		my @classes = keys %{$grouped_classes{$class_yr}};
		
		$classes_select .= "<TD>";
		for my $class (sort {$a cmp $b} @classes) {
			$classes_select .= qq{<INPUT type="checkbox" name="class_$class" value="$class"><LABEL for="class_$class">$class</LABEL><BR>};
		}
	}
	$classes_select .= "</TABLE>";

	my $current_yr = (localtime)[5] + 1900; 
	
	my $conf_code = gen_token();
	$session{"confirm_code"} = $conf_code;


	$content =
qq*
<!DOCTYPE html>
<html lang="en">
<head>

<SCRIPT type="text/javascript">

var num_re = /^[0-9]{0,4}\$/;

function check_fy() {

	var in_fy = document.getElementById("fy").value;

	if ( in_fy.match(num_re) ) {
		document.getElementById("fy_err").innerHTML = "";
	}
	else {
		document.getElementById("fy_err").innerHTML = "\*";
	}

}

</SCRIPT>

<title>Spanj::Accounts Management Information System::Prepare Fee Register</title>
</head>
<body>

$header
$feedback

<FORM method="POST" action="/cgi-bin/fee_register.cgi">

<input type="hidden" name="confirm_code" value="$conf_code">
<h4>Class</h4>
$classes_select
<h4>Financial Year</h4>

<span style="color: red" id="fy_err"></span><LABEL for="">Financial Year</LABEL>&nbsp;<INPUT type="text" name="fy" id="fy" value="$current_yr" onkeyup="check_fy()" onmouseover="check_fy()">


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
$con->rollback();
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
			$formatted_num = $sign . $formatted_num;
			$formatted_num .= $cents;
		}


	}
	return $formatted_num;

}
